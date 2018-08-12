#!/bin/sh

cd ~/NUEL-Bot
echo "[$(date +"%Y-%m-%d %H:%M")] ------" >> "out.log"
echo "[$(date +"%Y-%m-%d %H:%M")] Starting the bot" >> "out.log"
tmux new-session -d -s bot "/usr/bin/python3 ~/NUEL-Bot/run.py"
