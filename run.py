# run.py

from os import listdir
from subprocess import call

while True:
    # check if the config file exists
    if 'config.cfg' in listdir():
        # file exists - run the bot as a subprocess
        call(['python3', 'bot.py'])
    else:
        # file doesn't exist - close the program
        print('Config file not found.')
        raise SystemExit
