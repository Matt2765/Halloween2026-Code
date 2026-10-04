from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from hauntsim.cloud import CloudStore, Conflict
from hauntsim.model import Project
from hauntsim.persistence import save, load


class Remote:
    def __init__(self):
        self.files = {}
        self.version = 0
        self.offline = False
        self.during_put = None

    def put(self, name, body, etag):
        if self.offline:
            raise OSError('offline')
        old = self.files.get(name)
        if (old and old[1] != etag) or (not old and etag):
            raise Conflict()
        self.version += 1
        version = f'"{self.version}"'
        self.files[name] = (body, version)
        if self.during_put:
            fn, self.during_put = self.during_put, None
            fn()
        return version

    def get(self, name):
        return self.files[name]

    def listing(self):
        return [(name, data[1], 'today') for name, data in self.files.items()]


class CloudTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.a = CloudStore(self.root / 'a.sqlite')
        self.b = CloudStore(self.root / 'b.sqlite')
        self.remote = Remote()

    def body(self, name):
        project = Project()
        project.name = name
        save(project, self.root / 'project.hauntsim')
        return (self.root / 'project.hauntsim').read_bytes()

    def test_offline_restart_and_second_machine(self):
        body = self.body('offline work')
        key = self.a.queue(body, 'Haunt.hauntsim')
        self.remote.offline = True
        with self.assertRaises(OSError):
            self.a.sync(self.remote, key)
        restarted = CloudStore(self.a.path)
        self.assertEqual(restarted.get(key)['body'], body)
        self.remote.offline = False
        restarted.sync(self.remote, key)
        self.b.sync(self.remote)
        self.assertEqual(load(BytesIO(self.b.rows()[0]['body'])).name, 'offline work')
        self.assertFalse(restarted.get(key)['pending'])

    def test_concurrent_edits_preserve_both_versions(self):
        key = self.a.queue(self.body('initial'), 'Haunt.hauntsim')
        self.a.sync(self.remote, key)
        self.b.sync(self.remote)
        second = self.b.rows()[0]['id']
        self.a.queue(self.body('machine A'), '', key)
        self.b.queue(self.body('machine B'), '', second)
        self.a.sync(self.remote, key)
        conflicts = self.b.sync(self.remote, second)
        self.assertEqual(len(conflicts), 1)
        names = {load(BytesIO(body)).name for body, _ in self.remote.files.values()}
        self.assertEqual(names, {'machine A', 'machine B'})
        self.assertIn('conflict', self.b.get(second)['name'])

    def test_save_during_upload_stays_pending(self):
        key = self.a.queue(self.body('first'), 'Haunt.hauntsim')
        newer = self.body('second')
        self.remote.during_put = lambda: self.a.queue(newer, '', key)
        self.a.sync(self.remote, key)
        self.assertTrue(self.a.get(key)['pending'])
        self.a.sync(self.remote, key)
        self.assertEqual(self.remote.files['Haunt.hauntsim'][0], newer)
        self.assertFalse(self.a.get(key)['pending'])

    def test_retry_after_lost_acknowledgement(self):
        body = self.body('saved')
        key = self.a.queue(body, 'Haunt.hauntsim')
        self.remote.put('Haunt.hauntsim', body, '')
        self.assertEqual(self.a.sync(self.remote, key), [])
        self.assertEqual(len(self.remote.files), 1)
        self.assertFalse(self.a.get(key)['pending'])

    def test_active_project_retains_base_version(self):
        key = self.a.queue(self.body('initial'), 'Haunt.hauntsim')
        self.a.sync(self.remote, key)
        original = self.a.get(key)
        self.remote.put('Haunt.hauntsim', self.body('elsewhere'), original['etag'])
        self.a.sync(self.remote, key)
        self.assertEqual(self.a.get(key)['etag'], original['etag'])
        self.a.queue(self.body('local edits'), '', key)
        self.assertTrue(self.a.sync(self.remote, key))


if __name__ == '__main__':
    unittest.main()
