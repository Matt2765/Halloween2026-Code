Installation instructions (Windows PowerShell)

1. Create and activate a venv (optional but recommended):

    python -m venv .venv
    .\.venv\Scripts\Activate.ps1

2. Upgrade pip and install requirements:

    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt

Notes:
- `pydub` requires `ffmpeg` for MP3 support. Download ffmpeg from https://ffmpeg.org/download.html and add its `bin` folder to your PATH.
- `sounddevice` and `soundfile` may need platform wheels or C libraries. If installation fails, try installing Microsoft Visual C++ Build Tools or use prebuilt wheels from PyPI.
- If you don't want a virtual environment, you can omit steps 1 and 2a.
