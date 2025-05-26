import os
import time
import threading
from datetime import datetime
from threading import Thread
from queue import Queue

from flask import Flask, send_from_directory, jsonify, render_template_string, request, abort
from flask_socketio import SocketIO
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from PIL import Image
from flask_compress import Compress

# Configuration
IMAGE_FOLDER = './photos'
THUMB_FOLDER = os.path.join(IMAGE_FOLDER, 'thumbs')
IMAGES_PER_PAGE = 12
THUMB_SIZE = (400, 400)  # max width/height of thumbnails

# Create thumbs folder if not exists
if not os.path.exists(THUMB_FOLDER):
    os.makedirs(THUMB_FOLDER)

# Flask setup
app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, logger=True)
Compress(app)

stop_event = threading.Event()

image_event_queue = Queue()

allowed_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.gif', '.webp'}

def allowed_file(filename):
    return os.path.splitext(filename)[1].lower() in allowed_extensions

def generate_thumbnail(filename):
    source_path = os.path.join(IMAGE_FOLDER, filename)
    thumb_path = os.path.join(THUMB_FOLDER, filename)
    if not os.path.exists(thumb_path):
        try:
            with Image.open(source_path) as img:
                img.thumbnail(THUMB_SIZE)
                img.save(thumb_path, quality=85, optimize=True)
                print(f"Thumbnail created: {thumb_path}")
        except Exception as e:
            print(f"Error generating thumbnail for {filename}: {e}")

def list_images():
    images = []
    for filename in os.listdir(IMAGE_FOLDER):
        if os.path.isfile(os.path.join(IMAGE_FOLDER, filename)) and allowed_file(filename):
            generate_thumbnail(filename)  # create thumbnail if missing
            filepath = os.path.join(IMAGE_FOLDER, filename)
            mod_time = os.path.getmtime(filepath)
            images.append({
                'filename': filename,
                'mod_date': datetime.fromtimestamp(mod_time).strftime('%d-%m-%Y - %H:%M:%S'),
                'mod_timestamp': mod_time
            })
    images.sort(key=lambda x: x['mod_timestamp'], reverse=True)
    return images

@app.route('/')
def index():
    html = '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Photo Server 📷</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; background: #fff; }
            h1 { text-align: center; }
            .gallery { display: flex; flex-wrap: wrap; gap: 20px; justify-content: center; }
            .item { height: 100%; cursor: pointer; background: #fff; border: 8px solid #ffffff; width: 420px; box-shadow: 1px 3px 10px 0px rgb(187 187 187 / 55%); border-radius: 12px; }
            .item img { width: 100%; height: auto; display: block; border-radius: 8px; }
            .date { font-weight: bold; margin: 10px 0 0; word-break: break-word; text-align: center; }
            .emoji { font-size: 40px; vertical-align: baseline; }
            a { text-decoration: none; color: inherit; }
            a:hover { color: #007BFF; }
            #loading { font-size: 20px; text-align: center; padding: 40px; color: #666; }
        </style>
    </head>
    <body>
        <h1>Photo Server <span class="emoji">📷</span></h1>
        <div class="gallery" id="gallery"></div>
        <div id="loading">Loading...</div>

        <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.8.1/socket.io.min.js"></script>
        <script>
            let page = 0;
            const perPage = {{ per_page }};
            let loading = false;
            let noMore = false;

            const gallery = document.getElementById('gallery');
            const loadingDiv = document.getElementById('loading');

            function loadImages() {
                if (loading || noMore) return;
                loading = true;
                loadingDiv.textContent = "Loading...";
                fetch('/api/images?page=' + page)
                    .then(response => response.json())
                    .then(data => {
                        if(data.images.length === 0) {
                            noMore = true;
                            loadingDiv.textContent = "No more images";
                            return;
                        }
                        data.images.forEach(img => {
                            const item = document.createElement('a');
                            item.href = `/view/${encodeURIComponent(img.filename)}`
                            item.className = 'item';
                            item.innerHTML = `
                                <img src="/thumbnails/${encodeURIComponent(img.filename)}" alt="${img.filename}" loading="lazy" >
                                <div class="date">${img.mod_date}</div>
                            `;
                            gallery.appendChild(item);
                        });
                        page++;
                        loading = false;
                        loadingDiv.textContent = "";
                    })
                    .catch(e => {
                        loadingDiv.textContent = "Error loading images";
                        loading = false;
                    });
            }

            loadImages();

            window.addEventListener('scroll', () => {
                if ((window.innerHeight + window.scrollY) >= (document.body.offsetHeight - 300)) {
                    loadImages();
                }
            });

            const socket = io();

            socket.on('connect', () => {
              console.log('WebSocket connected, id:', socket.id);
              socket.emit('message', {data: 'Connected: ' + socket.id});
            });
            socket.on('disconnect', () => {
              console.log('WebSocket disconnected');
            });
            socket.on('update', (data) => {
                console.log('New image detected:', data.image.filename);
                
                // Build new image item element
                const img = data.image;
                const item = document.createElement('a');
                item.href = `/view/${encodeURIComponent(img.filename)}`;
                item.className = 'item';
                item.innerHTML = `
                    <img src="/images/${encodeURIComponent(img.filename)}" alt="${img.filename}" loading="lazy" >
                    <div class="date">${img.mod_date}</div>
                `;

                // Insert new image at the top of the gallery
                gallery.insertBefore(item, gallery.firstChild);
            });
            socket.on('connect_error', (err) => {
              console.log('Connection error:', err);
            });
            socket.on('error', (err) => {
              console.log('Socket error:', err);
            });
        </script>
    </body>
    </html>
    '''
    return render_template_string(html, per_page=IMAGES_PER_PAGE)

@app.route('/api/images')
def api_images():
    try:
        page = int(request.args.get('page', 0))
    except ValueError:
        page = 0
    images = list_images()
    start = page * IMAGES_PER_PAGE
    end = start + IMAGES_PER_PAGE
    return jsonify({'images': images[start:end]})

@app.route('/images/<filename>')
def serve_image(filename):
    if not allowed_file(filename):
        abort(404)
    response = send_from_directory(IMAGE_FOLDER, filename)
    response.headers["Content-Encoding"] = "identity"
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response

@app.route('/thumbnails/<filename>')
def serve_thumbnail(filename):
    if not allowed_file(filename):
        abort(404)
    return send_from_directory(THUMB_FOLDER, filename)

@app.route('/view/<filename>')
def image_page(filename):
    if not allowed_file(filename) or not os.path.isfile(os.path.join(IMAGE_FOLDER, filename)):
        abort(404)
    filepath = os.path.join(IMAGE_FOLDER, filename)
    mod_time = os.path.getmtime(filepath)
    mod_date = datetime.fromtimestamp(mod_time).strftime('%d-%m-%Y - %H:%M:%S')
    html = '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>{{ filename }}</title>
        <style>
            body { display: flex; align-items: center; justify-content: center; flex-direction: column; width: 100%; margin: 0; font-family: Arial, sans-serif; background: #fff; text-align: center; }
            img { width: 100%; max-height: 80vh; border-radius: 8px; }
            .container { width: 100%; max-width: fit-content; margin: 10px; }
            .info { margin-top: 15px; font-size: 1.1em; }
            .buttons { display: flex; justify-content: space-between; margin-top: 20px; }
            a.button {
                display: inline-block;
                padding: 10px 20px;
                background-color: #007BFF;
                color: white;
                text-decoration: none;
                font-size: 30px;
                border-radius: 8px;
                font-weight: bold;
            }
            a.button:hover {
                background-color: #0056b3;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>{{ mod_date }}</h1>
            <img src="{{ url_for('serve_image', filename=filename) }}" alt="{{ filename }}">
            <div class="buttons">
                <a href="{{ url_for('index') }}" class="button">Back to Gallery</a>
                <a href="{{ url_for('serve_image', filename=filename) }}" download target="_blank" class="button">Download</a>
            </div>
        </div>
    </body>
    </html>
    '''
    return render_template_string(html, filename=filename, mod_date=mod_date)

@socketio.on('message')
def handle_message(data):
    print('received message: ' + str(data))

class ImageFolderHandler(FileSystemEventHandler):
    def __init__(self):
        super().__init__()
        self._last_emit = 0

    def on_created(self, event):
        if not event.is_directory and allowed_file(event.src_path):
            now = time.time()
            if now - self._last_emit > 1:
                print(f"New image detected: {event.src_path}")
                filename = os.path.basename(event.src_path)
                generate_thumbnail(filename)  # generate thumbnail for new image immediately
                image_event_queue.put('new_image')
                self._last_emit = now

def get_latest_image():
    images = list_images()
    return images[0] if images else None

def background_emit_loop():
    while True:
        try:
            event = image_event_queue.get(timeout=1)  # wait max 1 second
            if event == 'new_image':
                latest_image = get_latest_image()
                if latest_image:
                    print("Emitting 'update' event with new image info")
                    socketio.emit('update', {'image': latest_image}, namespace='/')
        except:
            socketio.sleep(0.1)

def start_watcher():
    event_handler = ImageFolderHandler()
    observer = Observer()
    observer.schedule(event_handler, path=IMAGE_FOLDER, recursive=False)
    observer.start()
    print("Started folder watcher.")
    try:
        while not stop_event.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()
        print("Folder watcher stopped.")


if __name__ == '__main__':
    watcher_thread = Thread(target=start_watcher, daemon=True)
    watcher_thread.start()

    socketio.start_background_task(background_emit_loop)
    try:
        socketio.run(app, host='0.0.0.0', port=8000)
    except KeyboardInterrupt:
        print("Shutting down server...")
    finally:
        stop_event.set()
        watcher_thread.join()
        print("Server stopped.")