# File: mp3_to_wav_ffmpeg.py
# Requires: ffmpeg installed and available on PATH (or set FFMPEG_EXE below)

import os
import shutil
import subprocess
from tkinter import Tk, filedialog

# Set to a full path if ffmpeg isn't on PATH, e.g.:
# FFMPEG_EXE = r"C:\ffmpeg\bin\ffmpeg.exe"
FFMPEG_EXE = "ffmpeg"

FFMPEG_EXE = r"C:\ffmpeg\bin\ffmpeg.exe"

# Options
RECURSIVE = False          # set True to convert files in subfolders too
OVERWRITE = False          # set True to overwrite existing WAVs

def ffmpeg_available() -> bool:
    exe = FFMPEG_EXE if os.path.isabs(FFMPEG_EXE) else shutil.which(FFMPEG_EXE)
    return exe is not None

def convert_one(mp3_path: str, wav_path: str) -> bool:
    """
    Convert one MP3 to WAV using ffmpeg.
    - 16-bit PCM, 44.1 kHz, stereo
    Returns True on success, False on failure.
    """
    cmd = [
        FFMPEG_EXE, "-hide_banner", "-loglevel", "error",
        "-y" if OVERWRITE else "-n",
        "-i", mp3_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "44100",
        "-ac", "2",
        wav_path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return True
        else:
            # Show ffmpeg's error if any
            err = (result.stderr or "").strip()
            if err:
                print(f"  ffmpeg error: {err}")
            return False
    except FileNotFoundError:
        print("  ERROR: ffmpeg executable not found.")
        return False

def convert_folder(folder_path: str):
    if not ffmpeg_available():
        print("ERROR: ffmpeg not found.\n"
              "Install from https://ffmpeg.org/download.html and add its /bin to PATH,\n"
              "or set FFMPEG_EXE at the top of this script to the full path to ffmpeg.exe.")
        return

    tasks = []
    if RECURSIVE:
        for root, _, files in os.walk(folder_path):
            for name in files:
                if name.lower().endswith(".mp3"):
                    tasks.append((root, name))
    else:
        for name in os.listdir(folder_path):
            if name.lower().endswith(".mp3"):
                tasks.append((folder_path, name))

    if not tasks:
        print("No MP3 files found.")
        return

    print(f"Converting {len(tasks)} file(s)...\n")
    done = 0
    for root, name in tasks:
        mp3_path = os.path.join(root, name)
        wav_path = os.path.join(root, os.path.splitext(name)[0] + ".wav")

        if not OVERWRITE and os.path.exists(wav_path):
            print(f"[SKIP] {name} -> {os.path.basename(wav_path)} (already exists)")
            continue

        print(f"[WORK] {name} -> {os.path.basename(wav_path)}")
        ok = convert_one(mp3_path, wav_path)
        if ok:
            print(f"[ OK ] {name}")
            done += 1
        else:
            print(f"[FAIL] {name}")

    print(f"\nDone. Converted {done}/{len(tasks)} files.")

def main():
    root = Tk()
    root.withdraw()
    folder = filedialog.askdirectory(title="Select Folder Containing MP3s")
    if folder:
        convert_folder(folder)
    else:
        print("No folder selected.")

if __name__ == "__main__":
    main()
