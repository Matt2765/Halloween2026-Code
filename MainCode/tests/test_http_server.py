"""Real socket regression checks without importing or operating hardware."""
import ast
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from pathlib import Path
import socket
import ssl
import threading
from types import SimpleNamespace
import unittest


def load_server():
    path = Path(__file__).resolve().parents[1] / "ui/http_server.py"
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    tree.body = [node for node in tree.body
                 if not isinstance(node, (ast.Import, ast.ImportFrom))
                 or (isinstance(node, ast.ImportFrom) and node.module == "http.server")
                 or (isinstance(node, ast.Import)
                     and all(alias.name == "threading" for alias in node.names))]
    scope = {"house": SimpleNamespace(DEBUG_INFO=False, systemState="ONLINE"),
             "log_event": lambda *args: None}
    exec(compile(tree, str(path), "exec"), scope)
    return scope


class HTTPServerTests(unittest.TestCase):
    def setUp(self):
        self.scope = load_server()
        self.scope.update(HOST="127.0.0.1", PORT=0)
        factory = self.scope["ThreadingHTTPServer"]
        created = threading.Event()
        accepted = threading.Event()
        self.accepted = accepted

        class TestServer(factory):
            def get_request(server):
                result = super().get_request()
                accepted.set()
                return result

        def create(*args):
            self.server = TestServer(*args)
            created.set()
            return self.server

        self.scope["ThreadingHTTPServer"] = create
        self.worker = threading.Thread(target=self.scope["HTTP_SERVER"], daemon=True)
        self.worker.start()
        self.assertTrue(created.wait(2))

    def tearDown(self):
        self.server.shutdown()
        self.worker.join(2)
        self.assertFalse(self.worker.is_alive())

    def get(self, path="/"):
        connection = HTTPConnection(*self.server.server_address, timeout=1)
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_idle_connection_does_not_block_page_loads(self):
        with socket.create_connection(self.server.server_address, timeout=1):
            self.assertTrue(self.accepted.wait(1))
            with ThreadPoolExecutor(max_workers=4) as pool:
                responses = list(pool.map(lambda _: self.get(), range(8)))
            for status, body in responses:
                self.assertEqual(status, 200)
                self.assertIn(b"Halloween Remote Control", body)

    def test_status_endpoint_returns_json_without_hardware_actions(self):
        import json
        expected = {"system": "ONLINE", "doors": [{"id": 1, "state": "OPEN"}]}
        self.scope["status_snapshot"] = lambda: expected
        status, body = self.get("/api/status")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), expected)

    def test_slow_hardware_does_not_block_page_or_emergency(self):
        started, release = threading.Event(), threading.Event()

        def slow_lights():
            started.set()
            release.wait(3)

        self.scope["toggleHouseLights"] = slow_lights
        with ThreadPoolExecutor(max_workers=1) as pool:
            action = pool.submit(self.get, "/ToggleHouseLights")
            try:
                self.assertTrue(started.wait(1))
                self.assertEqual(self.get()[0], 200)
                self.assertEqual(self.get("/EMERGENCY_SHUTOFF")[0], 200)
                self.assertEqual(self.scope["house"].systemState, "EmergencyShutoff")
            finally:
                release.set()
            self.assertEqual(action.result()[0], 200)

    def test_incomplete_request_times_out(self):
        self.assertEqual(self.scope["HalloweenHTTP"].timeout, 10)
        self.scope["HalloweenHTTP"].timeout = 0.1
        with socket.create_connection(self.server.server_address, timeout=1) as client:
            client.sendall(b"GET / HTTP/1.0\r\nX-Incomplete:")
            self.assertEqual(client.recv(1024), b"")
        self.assertEqual(self.get()[0], 200)

    def test_https_handshake_is_rejected_promptly_with_useful_message(self):
        messages = []
        self.scope["log_event"] = messages.append
        incoming, outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
        client_tls = ssl.create_default_context().wrap_bio(
            incoming, outgoing, server_hostname="localhost")
        with self.assertRaises(ssl.SSLWantReadError):
            client_tls.do_handshake()
        with socket.create_connection(self.server.server_address, timeout=1) as client:
            client.sendall(outgoing.read())
            self.assertEqual(client.recv(1024), b"")
        self.assertTrue(any("HTTPS attempted" in message and "http://127.0.0.1:" in message
                            for message in messages))
        self.assertEqual(self.get()[0], 200)


if __name__ == "__main__":
    unittest.main()
