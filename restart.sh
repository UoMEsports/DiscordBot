#!/bin/sh

echo "[$(date +"%Y-%m-%d %H:%M")] Killing the bot's session" >> "out.log"
echo "[$(date +"%Y-%m-%d %H:%M")] ------" >> "out.log"
tmux kill-session -t bot

~/NUEL-Bot/start.sh
