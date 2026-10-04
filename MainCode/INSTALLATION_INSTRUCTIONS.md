Windows setup

Install Python 3 on the computer, then open this project in VS Code and run
`MainCode/main.py`. On its first run, the program creates a `.venv` in the
project folder, installs packages from `MainCode/requirements.txt`, and restarts
inside that environment. Later runs check the requirements file and repair any
missing packages automatically.

The first run needs an internet connection to download Python packages. `pydub`
needs FFmpeg on PATH for MP3 handling. The haunt's Arduino, audio, and network
hardware also need to be connected and configured for that computer.
