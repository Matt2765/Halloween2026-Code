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
from unittest.mock import patch
from types import ModuleType
import sys
import json


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

    def test_test_catalog_and_post_validation(self):
        module = ModuleType("control.web_tests")
        module.catalog = lambda: {"relays": [{"id": "cabin_strobe"}]}
        seen = []
        def execute(request):
            seen.append(request)
            if request.get("kind") == "invalid":
                raise ValueError("Unknown test control")
            return {"message": "Command sent"}
        module.execute = execute
        with patch.dict(sys.modules, {"control.web_tests": module}):
            status, body = self.get("/api/tests")
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body), module.catalog())
            for request, expected in (({"kind":"relay", "id":"cabin_strobe", "value":True},200),
                                      ({"kind":"animatronic", "id":"george", "value":"pose", "outputs":{"neck":90}},200),
                                      ({"kind":"invalid"},400)):
                connection = HTTPConnection(*self.server.server_address, timeout=1)
                try:
                    connection.request("POST", "/api/tests", body=json.dumps(request),
                                       headers={"Content-Type":"application/json"})
                    response = connection.getresponse()
                    self.assertEqual(response.status, expected)
                    self.assertIsInstance(json.loads(response.read()), dict)
                finally:
                    connection.close()
            self.assertEqual(seen[0]["id"], "cabin_strobe")

    def test_room_states_are_live_house_values_on_the_mains_page(self):
        house = self.scope["house"]
        house.HouseActive, house.houseLights = False, True
        house.DoorState, house.TargetDoorState = {}, {}
        rooms = self.scope["ROOM_STATES"]
        for room, _ in rooms:
            setattr(house, room + "_state", "INACTIVE")
        house.CabinRoom_state = "ACTIVE"
        house.Bathroom_state = "STANDBY"
        rsm = SimpleNamespace(
            get_value=lambda *args: None, device_status=lambda *args: {},
            get_button_value=lambda *args: None, get_pir_state=lambda *args: {},
            get_servo_state=lambda *args: {}, get_lantern_state=lambda *args: {},
            healthy=lambda: {}, command_failure=lambda: None,
        )
        control = ModuleType("control")
        control.remote_sensor_monitor = rsm
        modules = {
            "control": control,
            "control.doors": SimpleNamespace(DOOR_SOLENOID_PINS={}, DOOR_SENSOR_IDS={},
                                              DOOR_SENSOR_BYPASS={}),
            "control.animatronic_service": SimpleNamespace(pedro_status=lambda: {"mode":"manual"},
                                                                george_status=lambda: {"mode":"off"}),
        }
        with patch.dict(sys.modules, modules):
            status, body = self.get("/api/status")
            self.assertEqual(status, 200)
            data = json.loads(body)
            self.assertEqual(data["animatronics"], {"pedro":{"mode":"manual"}, "george":{"mode":"off"}})
            states = {r["id"]: r["state"] for r in data["rooms"]}
            self.assertEqual(len(states), 7)
            self.assertEqual(states["CabinRoom"], "ACTIVE")
            self.assertEqual(states["Bathroom"], "STANDBY")
            house.Bathroom_state = "INACTIVE"
            _, body = self.get("/api/status")
            states = {r["id"]: r["state"] for r in json.loads(body)["rooms"]}
            self.assertEqual(states["Bathroom"], "INACTIVE")
        status, page = self.get()
        self.assertEqual(status, 200)
        self.assertIn(b'id="roomStates"', page)
        self.assertIn(b'renderRoomStates(s.rooms||[])', page)

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
