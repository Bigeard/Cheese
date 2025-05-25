# Cheese - Photo Booth

*Say cheese!* A photo will be taken using a Camera (like a Nikon), a Webcam, or other devices.
You can also run a server to download the photos.

## Linux Installation

```bash
sudo apt-get install v4l-utils
v4l2-ctl --list-devices # List connected video devices

sudo apt-get install gphoto2
gphoto2 --auto-detect # List all connected cameras compatible with gphoto2
```

## Python Environment Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

## Voice Recognition Setup

```bash
wget https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
unzip vosk-model-small-en-us-0.15.zip
```
Why use Vosk? Because it's easy to use and perfect for low-performance computers.
Want more models? Visit: [https://alphacephei.com/vosk/models](https://alphacephei.com/vosk/models)

## Useful Command Line for Testing

Use this command to disconnect other apps using the camera (to avoid bugs/errors):

```bash
killall gvfs-gphoto2-volume-monitor gvfsd-gphoto2
```

This command (used in `start_cheese.sh`) initializes the `DSLR Virtual Cam` on `/dev/video10`:
```bash
sudo modprobe v4l2loopback video_nr=10 card_label="DSLR Virtual Cam" exclusive_caps=1
```

Start the camera stream and send it to the virtual camera device `/dev/video10`:
After executing this, you can use the video stream in apps like ffplay, VLC, web apps, etc.
```bash
gphoto2 --capture-movie --stdout | \
ffmpeg -f mjpeg -i - \
  -vf "scale=1280:852" \
  -vcodec rawvideo -pix_fmt yuv420p -r 30 \
  -f v4l2 /dev/video10
```

To display the video stream:
```bash
ffplay /dev/video10
```

To get all the configurations of your camera:
```bash
gphoto2 --list-config
```

For more detailed information:
```bash
gphoto2 --list-config | grep "/main/imgsettings" | while read line; do
  echo -e "\n=== $line ==="
  gphoto2 --get-config "$line"
done

gphoto2 --list-config | grep "/main/capturesettings" | while read line; do
  echo -e "\n=== $line ==="
  gphoto2 --get-config "$line"
done
```

## Run the Project

```bash
chmod +x start.sh # Make the script executable
./start.sh # Start the application!
```

You can also run the server and photo booth separately:
```bash
python cheese.py
python server.py
```