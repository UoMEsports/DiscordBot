#!/bin/sh

echo "[$(date +"%Y-%m-%d %H:%M")] Killing the bot's session" >> "out.log"
echo "[$(date +"%Y-%m-%d %H:%M")] ------" >> "out.log"
tmux kill-session -t bot

echo "[$(date +"%Y-%m-%d %H:%M")] Backing up the config file" >> "out.log"
cp ~/backups/config_2.cfg ~/backups/config_3.cfg
cp ~/backups/config_1.cfg ~/backups/config_2.cfg
cp ~/NUEL-Bot/config.cfg ~/backups/config_1.cfg

echo "[$(date +"%Y-%m-%d %H:%M")] Backing up the strikes file" >> "out.log"
cp ~/backups/strikes_2.csv ~/backups/strikes_3.csv
cp ~/backups/strikes_1.csv ~/backups/strikes_2.csv
cp ~/NUEL-Bot/strikes.csv ~/backups/strikes_1.csv

~/NUEL-Bot/start.sh
