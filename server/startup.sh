#!/bin/bash
cd /home/pi/basecamp
python server/logger.py >> logs/logger.log 2>&1 &
python server/presence.py >> logs/presence.log 2>&1 &
python server/audio.py >> logs/audio.log 2>&1 &
echo "All daemons started"
