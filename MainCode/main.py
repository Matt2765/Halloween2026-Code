# main.py
from pathlib import Path
import hashlib
import subprocess
import sys
from utils.tools import log_event

MAIN_CODE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MAIN_CODE_DIR.parent
VENV_DIR = PROJECT_ROOT / ".venv"
VENV_PYTHON = VENV_DIR / "Scripts" / "python.exe" if sys.platform == "win32" else VENV_DIR / "bin" / "python"
REQUIREMENTS = MAIN_CODE_DIR / "requirements.txt"

for import_root in (str(PROJECT_ROOT), str(MAIN_CODE_DIR)):
    if import_root not in sys.path:
        sys.path.insert(0, import_root)


def enter_project_venv():
    """Create the project environment and rerun here when launched externally."""
    if Path(sys.prefix).resolve() != VENV_DIR.resolve():
        if not VENV_PYTHON.is_file():
            print(f"Creating virtual environment at {VENV_DIR}...")
            subprocess.check_call([sys.executable, "-m", "venv", str(VENV_DIR)], cwd=PROJECT_ROOT)

        raise SystemExit(subprocess.call(
            [str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]],
            cwd=PROJECT_ROOT,
        ))

    requirements_hash = hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()
    hash_file = VENV_DIR / ".requirements.sha256"
    installed_hash = hash_file.read_text(encoding="utf-8").strip() if hash_file.is_file() else None
    pip_check = subprocess.run(
        [sys.executable, "-m", "pip", "check"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if requirements_hash != installed_hash or pip_check.returncode != 0:
        print("Installing Python packages from MainCode/requirements.txt...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS)],
            cwd=PROJECT_ROOT,
        )
        hash_file.write_text(requirements_hash, encoding="utf-8")


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
    enter_project_venv()
    from control.system import initialize_system
    log_event(f"SEVILLE MANOR - Copyright (c) 2025 Matthew Ruiz All Rights Reserved. Version {get_git_version()}")
    # Start main thread
    initialize_system()
