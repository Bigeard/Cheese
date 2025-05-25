import subprocess
import threading 
import signal
import time
import os
import queue
import json
import cv2
import sounddevice as sd
import vosk
import fcntl
from datetime import datetime
import numpy as np
from PIL import Image, ImageDraw, ImageFont


# === Config ===
PHOTO_DIR = "photos"
BLOCKSIZE = 4000
SCREEN_WIDTH = 1920
SCREEN_HEIGHT = 1080
BACKGROUND_COLOR = (255, 255, 255) # Azur: (230, 216, 173) # White: (255, 255, 255)

# Audio - Vosk
AUDIO_INPUT = "0" # `manual` or entre the index `0` or `5` or else 
MODEL_PATH = "vosk-model-small-en-us-0.15"
TRIGGERS = {"cheese", "cheers", "choose", "she", "she's", "geez", "news", "he's", "gee is", "gee", "key", "teams", "these"}

# Cam
IS_WEBCAM = False
WEBCAM_DEVICE = "/dev/video0"
VIRTUAL_CAM_DEVICE = "/dev/video10"
CAMERA_USB_PORT = "Auto"  # `Auto` change the port based on `gphoto2 --auto-detect` - ex: `001,037`

# Camera Setting (gphoto2)
WHITEBALANCE = "Automatic" # Easy to let camera adapt to unknown lighting
FLASHMODE = "Auto" # On / Off / Auto (Always good to have, I think so)
SHUTTERSPEED = "1/100" # Minimal movement (standing still, blinking) with flash = 1/60s – 1/125s. The longer the better for the light, but it can be blurred if you have movement.
ISO = "400" # Choose 100-800 depending on the environment (higher for a dark environment)
APERTURE = "4" # f/X - Single person, dark environment = f/2.8, 1–2 people, front-facing = f/4 or f/5.6, Group photo (3+ people) = f/8
EXPOSURE_COMPENSATION = "0.0" # If you want even less/more light: -1.0 to +1.0
KEEP_RAW = True # Keep raw image in the SD card of the camera
IMAGESIZE = "4928x3264"
COLORSPACE = "AdobeRGB"
ISOAUTO = "False"

# === Ensure folders exist ===
if not os.path.exists(MODEL_PATH):
    print(f"❌- Model folder '{MODEL_PATH}' not found.")
    exit()

if not os.path.exists(PHOTO_DIR):
    os.makedirs(PHOTO_DIR)


# === USB reset helper ===
if(not IS_WEBCAM):
    if(CAMERA_USB_PORT == "Auto"):
        output = subprocess.check_output(["gphoto2", "--auto-detect"], text=True)
        CAMERA_USB_PORT = [
            line.rsplit('  ', 1)
            for line in output.strip().split('\n')[2:]
            if line.strip()
        ][0][1].removeprefix("usb:")
    print("Camera USB port:", CAMERA_USB_PORT)

def usb_reset():
    usb_path = f"/dev/bus/usb/{CAMERA_USB_PORT.split(',')[0]}/{int(CAMERA_USB_PORT.split(',')[1]):03d}"
    try:
        with open(usb_path, 'wb') as fd:
            USBDEVFS_RESET = 21780
            fcntl.ioctl(fd, USBDEVFS_RESET, 0)
        print(f"🔌- USB device {usb_path} reset")
    except Exception as e:
        print(f"⚠️- Failed to reset USB device: {e}")

def resize_to_fit_screen(img, max_width, max_height):
    h, w = img.shape[:2]
    scale = min(max_width / w, max_height / h)
    new_size = (int(w * scale), int(h * scale))
    return cv2.resize(img, new_size, interpolation=cv2.INTER_AREA)


# === Configure camera for photo ===
def configure_camera(isPhoto):
    args = [
        "gphoto2",
        "--set-config", "capturetarget=1",
        "--set-config", "/main/actions/viewfinder=" + ("1" if not isPhoto else "0"),
        "--set-config", "/main/imgsettings/whitebalance=" + WHITEBALANCE,
        "--set-config", "/main/capturesettings/flashmode=" + FLASHMODE,
        "--set-config", "/main/capturesettings/shutterspeed2=" + SHUTTERSPEED, # You have also `shutterspeed`
        "--set-config", "/main/imgsettings/iso=" + ISO,
        "--set-config", "/main/capturesettings/f-number=" + APERTURE,
        "--set-config", "/main/capturesettings/exposurecompensation=" + EXPOSURE_COMPENSATION,
        "--set-config", "/main/capturesettings/nikonflashmode=iTTL",
        "--set-config", "/main/capturesettings/imagequality=" + ("NEF+Fine" if KEEP_RAW else "JPEG Fine"), # Raw and JPEG quality
        "--set-config", "/main/imgsettings/imagesize=" + IMAGESIZE,
        "--set-config", "/main/imgsettings/colorspace=" + COLORSPACE,
        "--set-config", "/main/imgsettings/isoauto=" + ISOAUTO,
        "--set-config", "/main/capturesettings/microphone=0"
    ]

    if(isPhoto): 
        print("📸- Configured camera for high-resolution photo")
    else:
        print("🎥- Configured camera for video/live view")
        args += ["--set-config", "/main/capturesettings/manualmoviesetting=1"]

    subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# === Capture photo with retries ===
def capture_photo(filename, frame=None, retries=3):
    if(IS_WEBCAM):
        cv2.imwrite(filename, frame)
        print(f"✅- Photo saved: {filename}")
        return True

    usb_reset()
    configure_camera(True)

    print(f"📸- Capturing high-resolution photo...")
    args = ["gphoto2", "--capture-image-and-download", f"--filename={filename}"] # "--wait-event-and-download=shutterclosed,timeout=3s"
    if(KEEP_RAW): args.append("--keep-raw")

    for attempt in range(1, retries + 1):
        result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print(f"📸- result:", result)
        if result.returncode == 0:
            print(f"✅- Photo saved: {filename}")
            return True
        else:
            print(f"⚠️- Attempt {attempt} failed: {result.stderr.decode().strip()}")
            time.sleep(1)
    print("❌- Failed to capture photo.")
    return False


# === Trigger match ===
def matches_trigger(text):
    text = text.lower().strip()
    return any(trigger in text for trigger in TRIGGERS)

# === Stream start/stop ===
def start_stream():
    if(IS_WEBCAM): return

    configure_camera(False)
    print("🎥- Starting DSLR virtual webcam stream...")
    stream_proc = subprocess.Popen([
        "bash", "-c",
        f"gphoto2 --capture-movie --stdout | ffmpeg -f mjpeg -i - "
        f"-vf scale=1280:852 -vcodec rawvideo -pix_fmt yuv420p -r 30 "
        f"-f v4l2 {VIRTUAL_CAM_DEVICE}"
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)

    time.sleep(2)  # Allow the stream to warm up
    return stream_proc

def stop_stream(proc):
    if(IS_WEBCAM): return

    print("🛑- Stopping stream...")
    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    proc.wait()
    # time.sleep(3)


# === Generate Image ===
def show_text(text):
    # Create a blank frame with OpenCV (White background)
    text_frame_cv = np.full((SCREEN_HEIGHT, SCREEN_WIDTH, 3), BACKGROUND_COLOR, dtype=np.uint8)

    # Convert the OpenCV image to a PIL image
    text_frame_pil = Image.fromarray(cv2.cvtColor(text_frame_cv, cv2.COLOR_BGR2RGB))

    # Load a custom font
    font = ImageFont.truetype("./RubikMonoOne-Regular.ttf", 100)  # Replace with the path to your font file

    # Draw the text on the PIL image
    draw = ImageDraw.Draw(text_frame_pil)
    frame_width, frame_height = text_frame_pil.size

    # Calculate the position to center the text
    text_width, text_height = draw.textlength(text, font=font), font.size
    position = ((frame_width - text_width) // 2, (frame_height - text_height) // 2)

    # Add the text to the image
    draw.text(position, text, font=font, fill=(0, 0, 0))

    # Convert the PIL image back to an OpenCV image
    text_frame_cv = cv2.cvtColor(np.array(text_frame_pil), cv2.COLOR_RGB2BGR)

    # Display the frame
    cv2.imshow('Camera', text_frame_cv)

def show_video(ret, frame):
    if ret:
        resized_frame = resize_to_fit_screen(frame, SCREEN_WIDTH, SCREEN_HEIGHT)  # Set your screen size
        cv2.imshow('Camera', resized_frame)


# === Main listener ===
def run_cheese_listener():
    # Load Audio Output (Mic)
    devices = sd.query_devices()
    input_devices = [d for d in devices if d['max_input_channels'] > 0]
    for idx, dev in enumerate(input_devices):
        print(f"[{idx}] {dev['name']}")
    # if AUDIO_INPUT == manual you can select the device you want to use
    if(AUDIO_INPUT == 'manual'): audio_index = int(input("\n🔧- Select audio input device number: "))
    else: audio_index = int(AUDIO_INPUT)
    real_audio_index = devices.index(input_devices[audio_index])
    sample_rate = input_devices[audio_index]['default_samplerate']
    print("Audio device selected:", input_devices[audio_index]['name'])

    # Load Vosk (voice detector)
    vosk.SetLogLevel(-1)
    model = vosk.Model(MODEL_PATH)
    q = queue.Queue()

    def audio_callback(indata, frames, time, status):
        q.put(bytes(indata))

    # Start stream on the Virtual Camera
    stream_proc = start_stream()

    # Start Video Capture
    cv2.namedWindow("Camera", cv2.WINDOW_NORMAL)
    cv2.setWindowProperty('Camera', cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    cap = cv2.VideoCapture(WEBCAM_DEVICE if IS_WEBCAM else VIRTUAL_CAM_DEVICE)
    if not cap.isOpened():
        if IS_WEBCAM:
            print(f"❌- Failed to open webcam {WEBCAM_DEVICE}")
            return

        print(f"❌- Failed to open virtual camera {VIRTUAL_CAM_DEVICE}")
        stop_stream(stream_proc)
        return

    # Start!
    print("You using the ", ("Webcam" if IS_WEBCAM else "Camera (gphoto2)"))
    print("🎧- Say 'cheese' to take a photo. Press ESC to exit.\n")
    ret, frame = cap.read()
    show_video(ret, frame)

    with sd.RawInputStream(samplerate=sample_rate, blocksize=BLOCKSIZE, dtype='int16',
                           channels=1, callback=audio_callback, device=real_audio_index):
        rec = vosk.KaldiRecognizer(model, sample_rate)
        
        while True:
            data = q.get()

            ret, frame = cap.read()
            show_video(ret, frame)

            if rec.AcceptWaveform(data):
                result = json.loads(rec.Result())
                text = result.get("text", "")
                print(f"🗣️- Heard: {text}")
                if matches_trigger(text):
                    cap.release()
                    stop_stream(stream_proc)
                    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                    filename = os.path.join(PHOTO_DIR, f"cheese_{timestamp}.jpg")
                    show_text("- READY -")
                    cv2.waitKey(800)
                    show_text("- DON'T MOVE -")
                    cv2.waitKey(400)

                    capture_thread = threading.Thread(target=capture_photo, args=(filename, frame))
                    capture_thread.start()

                    cv2.waitKey(400)
                    show_text("- ! CHEESE ! -")
                    cv2.waitKey(1)
                    cv2.waitKey(2200)
                    show_text("Wait...")
                    cv2.waitKey(1)

                    capture_thread.join()

                    img = cv2.imread(filename)
                    if img is not None:
                        resized_img = resize_to_fit_screen(img, SCREEN_WIDTH, SCREEN_HEIGHT)  # Set your screen size
                        cv2.imshow("Camera", resized_img)
                        cv2.waitKey(2200)

                    stream_proc = start_stream()
                    # time.sleep(5)  # Give camera and ffmpeg time to initialize

                    # Try reopening the video stream
                    for i in range(10):
                        cv2.namedWindow('Camera', cv2.WINDOW_NORMAL)
                        cv2.setWindowProperty('Camera', cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
                        cap = cv2.VideoCapture(WEBCAM_DEVICE if IS_WEBCAM else VIRTUAL_CAM_DEVICE)
                        if cap.isOpened():
                            print("✅- Video stream restarted.")
                            break
                        else:
                            print(f"⏳- Waiting for video stream to restart... ({i+1}/10)")
                            time.sleep(1)
                    else:
                        print("❌- Failed to restart video stream after photo.")

            key = cv2.waitKey(1) & 0xFF
            if key == 27 or key == ord('q'):
                print("🛑- ESC or 'Q' pressed. Exiting.")
                stop_stream(stream_proc)
                cap.release()
                cv2.destroyAllWindows()
                break

# === Run the system ===
if __name__ == "__main__":
    run_cheese_listener()
