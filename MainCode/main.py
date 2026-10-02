# main.py
from pathlib import Path
import subprocess
import sys
from utils.tools import log_event

MAIN_CODE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MAIN_CODE_DIR.parent
for import_root in (str(PROJECT_ROOT), str(MAIN_CODE_DIR)):
    if import_root not in sys.path:
        sys.path.insert(0, import_root)

def get_git_version():
    try:
        version = subprocess.check_output(
            ["git", "describe", "--tags", "--always"],
            stderr=subprocess.STDOUT
        ).decode().strip()
        return version
    except Exception:
        return "unknown-version"

if __name__ == "__main__":
    from control.system import initialize_system
    log_event(f"SEVILLE MANOR - Copyright (c) 2025 Matthew Ruiz All Rights Reserved. Version {get_git_version()}")
    # Start main thread
    initialize_system()
