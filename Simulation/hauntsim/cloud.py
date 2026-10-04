"""Nextcloud transport and durable offline queue, independent of the GUI."""
from contextlib import closing
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import sqlite3
import uuid
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError
from urllib.parse import quote, unquote, urlsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
import zipfile
from .persistence import load

SHARE_URL = 'https://storage.aimlessworksdrive.space/s/K6QniDyteowwaNt'
MAX_BYTES = 100_000_000


class Conflict(Exception):
    pass


class Nextcloud:
    def __init__(self, share=SHARE_URL):
        parts = urlsplit(share)
        prefix, token = parts.path.rstrip('/').rsplit('/s/', 1)
        if parts.scheme != 'https' or not token or '/' in token:
            raise ValueError('Expected an HTTPS Nextcloud folder share link')
        self.base = f'{parts.scheme}://{parts.netloc}{prefix}/public.php/dav/files/{quote(token)}/'

    def request(self, method, name='', data=None, headers=None):
        request = Request(self.base + quote(name, safe=''), data=data, method=method,
                          headers={'X-Requested-With': 'XMLHttpRequest', **(headers or {})})
        try:
            with urlopen(request, timeout=20) as response:
                body = response.read(MAX_BYTES + 1)
                if len(body) > MAX_BYTES:
                    raise ValueError('Cloud file exceeds 100 MB')
                return body, response.headers.get('ETag', '')
        except HTTPError as exc:
            exc.close()
            if exc.code in (404, 412) and method == 'PUT':
                raise Conflict() from exc
            raise

    def listing(self):
        body, _ = self.request('PROPFIND', headers={'Depth': '1'})
        root = ET.fromstring(body)
        result = []
        for response in root.findall('{DAV:}response'):
            href = unquote(urlsplit(response.findtext('{DAV:}href', '')).path)
            name = href.rstrip('/').rsplit('/', 1)[-1]
            for stat in response.findall('{DAV:}propstat'):
                if ' 200 ' not in stat.findtext('{DAV:}status', ''):
                    continue
                prop = stat.find('{DAV:}prop')
                if prop is None or prop.find('.//{DAV:}collection') is not None:
                    continue
                if name.lower().endswith('.hauntsim'):
                    result.append((name, prop.findtext('{DAV:}getetag', ''),
                                   prop.findtext('{DAV:}getlastmodified', '')))
        return result

    def get(self, name):
        body, etag = self.request('GET', name)
        try:
            load(BytesIO(body))  # Validate before allowing a remote file into the cache.
        except (ValueError,KeyError,TypeError,zipfile.BadZipFile,RuntimeError) as exc:
            raise ValueError(f'Invalid cloud project: {exc}') from exc
        return body, etag

    def put(self, name, body, etag):
        headers = {'Content-Type': 'application/octet-stream'}
        headers['If-Match' if etag else 'If-None-Match'] = etag or '*'
        _, new_etag = self.request('PUT', name, body, headers)
        if not new_etag:
            downloaded, new_etag = self.get(name)
            if downloaded != body or not new_etag:
                raise RuntimeError('Could not verify the uploaded version; kept local save pending')
        return new_etag


class CloudStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY, name TEXT UNIQUE, body BLOB NOT NULL,
                etag TEXT NOT NULL, pending INTEGER NOT NULL, revision INTEGER NOT NULL,
                modified TEXT NOT NULL)''')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def rows(self, bodies=True):
        with closing(self.connect()) as db:
            columns='*' if bodies else 'id,name,etag,pending,revision,modified'
            return [dict(row) for row in db.execute(f'SELECT {columns} FROM projects ORDER BY modified DESC')]

    def get(self, key):
        with closing(self.connect()) as db:
            row = db.execute('SELECT * FROM projects WHERE id=?', (key,)).fetchone()
            return dict(row) if row else None

    def queue(self, body, name, key=None):
        load(BytesIO(body))
        now = datetime.now(timezone.utc).isoformat(timespec='seconds')
        with closing(self.connect()) as db, db:
            if key:
                if not db.execute('UPDATE projects SET body=?,pending=1,revision=revision+1,modified=? WHERE id=?',
                                  (body, now, key)).rowcount:
                    raise ValueError('Local cloud project is missing')
            else:
                key = uuid.uuid4().hex
                db.execute('INSERT INTO projects VALUES (?,?,?,?,?,?,?)', (key, name, body, '', 1, 1, now))
        return key

    def sync(self, remote, active=None):
        conflicts = []
        self.issues=[]
        self.remote_updates=[]
        for row in self.rows():
            if not row['pending']:
                continue
            name, etag = row['name'], row['etag']
            try:
                new_etag = remote.put(name, row['body'], etag)
            except Conflict:
                # An interrupted acknowledgement can leave an already uploaded save queued.
                try:
                    current, current_etag = remote.get(name)
                except HTTPError as exc:
                    if exc.code != 404:
                        raise
                    current, current_etag = None, ''
                except ValueError:
                    # A corrupt remote file must not prevent preserving local work.
                    current, current_etag = None, ''
                if current == row['body'] and current_etag:
                    new_etag = current_etag
                else:
                    name = f'{Path(name).stem} (conflict {uuid.uuid4().hex[:8]}).hauntsim'
                    # Persist the recovery destination before writing, so retries are idempotent.
                    with closing(self.connect()) as db, db:
                        db.execute('UPDATE projects SET name=?,etag=? WHERE id=?', (name, '', row['id']))
                    new_etag = remote.put(name, row['body'], '')
                    conflicts.append(name)
            with closing(self.connect()) as db, db:
                db.execute('''UPDATE projects SET etag=?,pending=CASE WHEN revision=? THEN 0 ELSE 1 END
                              WHERE id=?''', (new_etag, row['revision'], row['id']))
        cached={r['name']:r for r in self.rows(bodies=False)}
        for name, etag, modified in remote.listing():
            local = cached.get(name)
            if local and local['id']==active and not local['pending'] and local['etag']!=etag:
                self.remote_updates.append(name)
            if local and (local['pending'] or local['id'] == active or local['etag'] == etag):
                continue
            try:
                body, actual_etag = remote.get(name)
            except (ValueError,KeyError,TypeError) as exc:
                self.issues.append(f'{name}: {exc}')
                continue
            if not actual_etag:
                raise RuntimeError('Server did not provide a version identifier')
            try:
                modified=parsedate_to_datetime(modified).isoformat(timespec='seconds')
            except (TypeError,ValueError):
                pass
            with closing(self.connect()) as db, db:
                if local:
                    db.execute('UPDATE projects SET body=?,etag=?,modified=? WHERE id=? AND pending=0',
                               (body, actual_etag, modified, local['id']))
                else:
                    db.execute('INSERT OR IGNORE INTO projects VALUES (?,?,?,?,?,?,?)',
                               (uuid.uuid4().hex, name, body, actual_etag, 0, 0, modified))
        return conflicts

    def refresh(self, remote, key):
        """Refresh only the selected project; unrelated failures cannot mask its latest save."""
        row=self.get(key)
        if not row:
            raise ValueError('Local cloud project is missing')
        if row['pending']:
            return row['body']
        body,etag=remote.get(row['name'])
        if not etag:
            raise ValueError('Server did not provide a version identifier')
        with closing(self.connect()) as db, db:
            db.execute('UPDATE projects SET body=?,etag=? WHERE id=? AND pending=0 AND revision=?',
                       (body,etag,key,row['revision']))
        return self.get(key)['body']
