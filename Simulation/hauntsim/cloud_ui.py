"""Cloud project browser and nonblocking sync coordinator."""
from io import BytesIO
import hashlib
import os
from pathlib import Path
import queue
import re
import tempfile
import threading
from PySide6.QtCore import QObject, QTimer, Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTreeWidget, QTreeWidgetItem, QInputDialog, QFileDialog)
from .cloud import CloudStore, Nextcloud
from .persistence import save, load


class CloudController(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.active = None
        self.busy = False
        self.results = queue.Queue()
        self.dialog = None
        self.status = 'Cloud ready'
        # Separate installations have separate queues, just like separate machines.
        install = hashlib.sha256(str(Path(__file__).resolve()).encode()).hexdigest()[:12]
        root = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local/share')))
        self.store = CloudStore(root / 'HauntSim' / 'cloud' / install / 'projects.sqlite3')
        self.remote = Nextcloud()
        self.label = QLabel(self.status)
        window.statusBar().addPermanentWidget(self.label)
        self.poll = QTimer(self)
        self.poll.setInterval(150)
        self.poll.timeout.connect(self.complete)
        self.poll.start()
        self.retry = QTimer(self)
        self.retry.setInterval(30000)
        self.retry.timeout.connect(self.sync)
        self.retry.start()
        QTimer.singleShot(500, self.sync)

    def run(self, function, callback):
        if self.busy:
            return False
        self.busy = True
        self.set_status('Syncing…')
        def work():
            try:
                self.results.put((callback, function(), None))
            except Exception as exc:
                self.results.put((callback, None, exc))
        threading.Thread(target=work, daemon=True).start()
        return True

    def set_status(self, text):
        self.status = text
        self.label.setText(text)
        if self.dialog:
            self.description.setText(text)

    def complete(self):
        try:
            callback, result, error = self.results.get_nowait()
        except queue.Empty:
            return
        self.busy = False
        if error:
            pending = sum(r['pending'] for r in self.store.rows(bodies=False))
            self.set_status(f'Cloud unavailable · {pending} saved locally, pending sync')
            self.label.setToolTip(str(error))
            if self.dialog:
                self.description.setText(self.status + '\n' + str(error))
        else:
            self.label.setToolTip('')
            pending = sum(r['pending'] for r in self.store.rows(bodies=False))
            self.set_status(f'{pending} saved locally, pending sync' if pending else 'Cloud up to date')
        callback(result, error)
        self.window.update_title()
        self.populate()

    def sync(self):
        active = self.active
        def done(conflicts, error):
            if conflicts:
                self.set_status('Both versions kept · conflict copy saved')
                self.window.notice('Another machine changed this project. Both versions were kept.\n\n'
                                   + '\n'.join(conflicts))
            elif not error and getattr(self.store,'remote_updates',[]):
                self.set_status('New cloud version available - reopen from Cloud projects')
            if not error and getattr(self.store,'issues',[]):
                self.set_status('Some cloud files could not be opened - see details')
                self.label.setToolTip('\n'.join(self.store.issues))
                if self.dialog:
                    self.description.setText(self.status+'\n'+'\n'.join(self.store.issues))
        return self.run(lambda: self.store.sync(self.remote, active), done)

    def save(self, copy=False):
        w = self.window
        key = None if copy else self.active
        name = ''
        if not key:
            name, accepted = QInputDialog.getText(w, 'Save to cloud', 'Project name:', text=w.project.name)
            if not accepted or not name.strip():
                return False
            name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name.strip())
            if not name.lower().endswith('.hauntsim'):
                name += '.hauntsim'
            if any(r['name'].casefold() == name.casefold() for r in self.store.rows(bodies=False)):
                w.notice('That name is already in your cloud projects. Open it to edit, or choose a different name.')
                return False
        try:
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'save.hauntsim'
                save(w.project, path)
                self.active = self.store.queue(path.read_bytes(), name, key)
            w.filename = ''
            w.dirty = False
            w.update_title()
            self.set_status('Saved locally · pending sync')
            if not self.sync():
                # A running upload may contain an older revision; follow it immediately.
                QTimer.singleShot(1000, self.sync_pending)
            self.populate()
            return True
        except Exception as exc:
            w.error(f'Could not save project:\n{exc}')
            return False

    def sync_pending(self):
        if self.busy:
            QTimer.singleShot(1000, self.sync_pending)
        elif any(r['pending'] for r in self.store.rows(bodies=False)):
            self.sync()

    def download(self):
        w = self.window
        filename, _ = QFileDialog.getSaveFileName(w, 'Download project copy',
            w.project.name + '.hauntsim', 'HauntSim (*.hauntsim)')
        if filename:
            try:
                save(w.project, filename if filename.lower().endswith('.hauntsim') else filename + '.hauntsim')
            except Exception as exc:
                w.error(exc)

    def browse(self):
        if self.dialog:
            self.dialog.raise_()
            return
        dialog = QDialog(self.window)
        self.dialog = dialog
        dialog.setWindowTitle('Cloud projects')
        dialog.resize(780, 420)
        layout = QVBoxLayout(dialog)
        self.description = QLabel(self.status)
        self.description.setWordWrap(True)
        layout.addWidget(self.description)
        layout.addWidget(QLabel('Saved projects are cached on this machine for offline use.'))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['Project', 'Status', 'Modified'])
        self.tree.setColumnWidth(0, 310)
        self.tree.setColumnWidth(1, 180)
        layout.addWidget(self.tree)
        buttons = QHBoxLayout()
        for text, callback in [('Refresh / sync', self.sync), ('Open project', self.open_selected), ('Close', dialog.accept)]:
            button = QPushButton(text)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.tree.itemDoubleClicked.connect(lambda *_: self.open_selected())
        self.populate()
        self.sync()
        dialog.exec()
        self.dialog = None
        dialog.deleteLater()

    def populate(self):
        if not self.dialog:
            return
        selected = self.tree.currentItem()
        key = selected.data(0, Qt.UserRole) if selected else None
        self.tree.clear()
        for row in self.store.rows(bodies=False):
            item = QTreeWidgetItem([row['name'], 'Pending upload' if row['pending'] else 'Available offline', row['modified']])
            item.setData(0, Qt.UserRole, row['id'])
            self.tree.addTopLevelItem(item)
            if row['id'] == key:
                self.tree.setCurrentItem(item)

    def open_selected(self):
        if self.busy:
            self.description.setText('Sync is running. You can open a project as soon as it finishes.')
            return
        item = self.tree.currentItem()
        if not item:
            return
        key = item.data(0, Qt.UserRole)
        if not self.window.confirm_unsaved():
            return
        if self.busy:  # Saving the previous project just started an upload.
            self.description.setText('Finishing your save. Select Open project again when sync finishes.')
            return
        self.dialog.accept()
        self.window.setEnabled(False)
        def fetch():
            return self.store.refresh(self.remote,key)
        def opened(body, error):
            self.window.setEnabled(True)
            try:
                if error:
                    body = self.store.get(key)['body']
                self.window.set_project(load(BytesIO(body)))
                self.active = key
                self.window.update_title()
                if error:
                    self.set_status('Offline · opened local copy')
            except Exception as exc:
                self.window.error(f'Could not open cloud project:\n{exc}')
        self.run(fetch, opened)

    def stop(self):
        self.retry.stop()
        self.poll.stop()
