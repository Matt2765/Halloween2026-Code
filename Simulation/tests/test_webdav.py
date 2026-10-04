"""Real HTTP requests against a local WebDAV fixture; never uses the user's server."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.parse import quote, unquote
from xml.sax.saxutils import escape
import unittest
from hauntsim.cloud import CloudStore, Nextcloud, Conflict
from hauntsim.persistence import save
from hauntsim.model import Project


class WebDAVTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files={}
        cls.version=0
        cls.requests=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):
                pass
            def respond(self,status,body=b'',etag=''):
                self.send_response(status)
                self.send_header('Content-Length',str(len(body)))
                if etag:
                    self.send_header('ETag',etag)
                self.end_headers()
                self.wfile.write(body)
            def record(self):
                cls.requests.append((self.command,self.path,dict(self.headers)))
                return unquote(self.path.removeprefix('/dav/'))
            def do_PROPFIND(self):
                self.record()
                if self.headers.get('Depth')!='1' or self.headers.get('X-Requested-With')!='XMLHttpRequest':
                    return self.respond(401)
                body='<d:multistatus xmlns:d="DAV:"><d:response><d:href>/dav/</d:href><d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>'
                for name,(data,etag) in cls.files.items():
                    body+=f'<d:response><d:href>/dav/{quote(name)}</d:href><d:propstat><d:prop><d:resourcetype/><d:getetag>{escape(etag)}</d:getetag><d:getlastmodified>Sun, 04 Oct 2026 12:00:00 GMT</d:getlastmodified></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>'
                self.respond(207,(body+'</d:multistatus>').encode())
            def do_GET(self):
                name=self.record()
                if name not in cls.files:
                    return self.respond(404)
                self.respond(200,*cls.files[name])
            def do_PUT(self):
                name=self.record()
                data=self.rfile.read(int(self.headers.get('Content-Length','0')))
                old=cls.files.get(name)
                if self.headers.get('X-Requested-With')!='XMLHttpRequest':
                    return self.respond(401)
                if (old and self.headers.get('If-Match')!=old[1]) or (not old and 'If-Match' in self.headers):
                    return self.respond(412)
                cls.version+=1
                etag=f'"v{cls.version}"'
                cls.files[name]=(data,etag)
                self.respond(201,etag=etag)
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.thread=Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.files.clear()
        self.requests.clear()
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        p=Project(name='Portable test')
        p.background=b'embedded asset'
        save(p,self.root/'project.hauntsim')
        self.body=(self.root/'project.hauntsim').read_bytes()
        self.remote=Nextcloud()
        self.remote.base=f'http://127.0.0.1:{self.server.server_port}/dav/'
        self.store=CloudStore(self.root/'cache.sqlite')

    def test_upload_list_download_unicode_and_conditional_updates(self):
        name='Halloween # & café.hauntsim'
        etag=self.remote.put(name,self.body,'')
        self.assertEqual(self.remote.get(name),(self.body,etag))
        self.assertEqual(self.remote.listing()[0][0],name)
        with self.assertRaises(Conflict):
            self.remote.put(name,self.body,'')
        with self.assertRaises(Conflict):
            self.remote.put(name,self.body,'"old"')
        self.assertNotEqual(self.remote.put(name,self.body,etag),etag)
        self.assertTrue(any('%23' in path and '%C3%A9' in path for _,path,_ in self.requests))

    def test_corrupt_cloud_file_does_not_block_valid_files(self):
        self.files['corrupt.hauntsim']=(b'not a zip','"broken"')
        self.remote.put('valid.hauntsim',self.body,'')
        self.store.sync(self.remote)
        self.assertEqual([r['name'] for r in self.store.rows()],['valid.hauntsim'])
        self.assertEqual(len(self.store.issues),1)
        with self.assertRaises(ValueError):
            self.remote.get('corrupt.hauntsim')

    def test_corrupt_remote_conflict_preserves_local_save(self):
        self.files['Haunt.hauntsim']=(b'bad data','"remote"')
        key=self.store.queue(self.body,'Haunt.hauntsim')
        conflicts=self.store.sync(self.remote,key)
        self.assertEqual(len(conflicts),1)
        self.assertEqual(self.remote.get(conflicts[0])[0],self.body)
        self.assertEqual(self.files['Haunt.hauntsim'][0],b'bad data')

    def test_deleted_remote_keeps_local_recovery_copy(self):
        key=self.store.queue(self.body,'Haunt.hauntsim')
        self.store.sync(self.remote,key)
        self.files.clear()
        self.store.queue(self.body,'',key)
        conflicts=self.store.sync(self.remote,key)
        self.assertEqual(len(conflicts),1)
        self.assertNotIn('Haunt.hauntsim',self.files)

    def test_active_remote_update_is_reported_and_refresh_fetches_latest(self):
        key=self.store.queue(self.body,'Haunt.hauntsim')
        self.store.sync(self.remote,key)
        other=Project(name='Other machine')
        save(other,self.root/'other.hauntsim')
        updated=(self.root/'other.hauntsim').read_bytes()
        self.remote.put('Haunt.hauntsim',updated,self.store.get(key)['etag'])
        self.store.sync(self.remote,key)
        self.assertEqual(self.store.remote_updates,['Haunt.hauntsim'])
        self.assertEqual(self.store.get(key)['body'],self.body)
        self.assertEqual(self.store.refresh(self.remote,key),updated)

    def test_cached_date_is_normalized(self):
        self.remote.put('Haunt.hauntsim',self.body,'')
        self.store.sync(self.remote)
        self.assertEqual(self.store.rows()[0]['modified'],'2026-10-04T12:00:00+00:00')


if __name__=='__main__':
    unittest.main()
