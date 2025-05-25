#!/bin/bash

sudo modprobe v4l2loopback video_nr=10 card_label="DSLR Virtual Cam" exclusive_caps=1

killall gvfs-gphoto2-volume-monitor gvfsd-gphoto2

source .venv/bin/activate
python server.py |
python cheese.py

