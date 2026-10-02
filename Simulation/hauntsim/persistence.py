"""Atomic ZIP project containers; assets are never extracted to disk."""
import json
import os
from pathlib import Path
import tempfile
import zipfile
from .model import Project


def save(project, filename):
    target = Path(filename).resolve()
    fd, temp = tempfile.mkstemp(prefix=target.name+'.', suffix='.tmp', dir=target.parent)
    try:
        with os.fdopen(fd, 'w+b') as stream:
            with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('project.json', json.dumps(project.data(), allow_nan=False))
                if project.background:
                    archive.writestr('assets/background', project.background)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def load(filename):
    with zipfile.ZipFile(filename) as archive:
        if sum(i.file_size for i in archive.infolist()) > 100_000_000:
            raise ValueError('Project exceeds the 100 MB uncompressed safety limit')
        data = json.loads(archive.read('project.json'))
        bg = archive.read('assets/background') if 'assets/background' in archive.namelist() else b''
        return Project.from_data(data, bg)
