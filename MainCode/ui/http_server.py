from http.server import HTTPServer, BaseHTTPRequestHandler
from MainCode.rooms import Room_1, Room_2, Room_3, Room_4
from control.doors import setDoorState
from control.houseLights import toggleHouseLights
from utils.tools import log_event
from context import house
from ui.gui import demoEvent
from MainCode.rooms import Room_5
import threading

HOST = "0.0.0.0"  # Listen on all interfaces
PORT = 9999

# ---------------------------------------------------------------------------
# HTML PAGE CONTENT
# ---------------------------------------------------------------------------
WEBPAGE = '''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>[year] Halloween Remote Control</title>
  <style>
    :root { --bg: #111; --panel: #1c1c1c; --text: #f5f5f5; --muted: #a0a0a0; --accent: #3b82f6; --warn: #f59e0b; --danger: #ef4444; --ok: #22c55e; --border: #2a2a2a; --shadow: 0 10px 18px rgba(0,0,0,.45); --radius: 18px; --gap: 12px; }
    * { box-sizing: border-box; }
    body { margin: 0; background: var(--bg); color: var(--text); font-family: system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif; }
    header { background:#2b2b2b; position: sticky; top:0; z-index: 20; padding: 10px 16px; box-shadow: var(--shadow); font-weight: 700; }
    main { padding: 16px; max-width: 760px; margin: 0 auto; }
    .section { background: var(--panel); border:1px solid var(--border); border-radius: var(--radius); padding: 14px; margin-bottom: 14px; box-shadow: var(--shadow); }
    .row { display:flex; gap: var(--gap); flex-wrap: wrap; }
    button { appearance: none; border: none; color: #fff; font-weight: 800; cursor: pointer; border-radius: 12px; padding: 16px 18px; min-width: 160px; flex: 1 1 220px; box-shadow: var(--shadow); transition: transform .06s ease, filter .12s ease, opacity .2s; }
    button:active { transform: translateY(1px) scale(0.997); }
    button[disabled] { opacity: .6; cursor: not-allowed; }
    .btn-danger { background: var(--danger); }
    .btn-primary { background: var(--accent); }
    .btn-warn { background: var(--warn); color:#1a1a1a; }
    .btn-secondary { background: #3a3a3a; }
    h2 { margin: 0 0 10px; font-size: 14px; font-weight: 800; text-transform: uppercase; color: var(--muted); letter-spacing: .12em; }
    .status { margin-top: 8px; font-size: 13px; color: var(--muted); display:flex; align-items:center; gap:8px; min-height: 22px; }
    .dot { width:10px; height:10px; border-radius:50%; background:#444; display:inline-block; }
    .dot.ok { background: var(--ok); }
    .dot.err { background: var(--danger); }
    .kbd { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; background:#000; padding:2px 6px; border-radius:6px; border:1px solid #2a2a2a; }
    .hero { background: var(--panel); padding: 12px; border-radius: var(--radius); border: 1px solid var(--border); margin-bottom: 16px; box-shadow: var(--shadow); }
    .hero .row button { flex: 1 1 100%; min-height: 64px; font-size: 18px; }
    .hero .row button + button { flex: 1 1 calc(50% - var(--gap)); min-height: 58px; font-size: 16px; }
    footer { text-align:center; color: #777; font-size: 12px; padding: 24px 12px; }
    .small { font-size: 12px; color: var(--muted); }
  </style>
</head>
<body>
  <header>[year] Halloween Remote Control App</header>
  <main>
    <section class="hero">
      <div class="row"><button class="btn-danger" data-endpoint="/EMERGENCY_SHUTOFF" data-confirm="true">EMERGENCY SHUTOFF</button></div>
      <div class="row" style="margin-top:12px">
        <button class="btn-primary" data-endpoint="/START">START HOUSE</button>
        <button class="btn-warn" data-endpoint="/SOFT_SHUTDOWN">SOFT SHUTDOWN</button>
      </div>
      <div class="status" id="status-hero"><span class="dot" id="dot-hero"></span><span id="msg-hero">Ready</span></div>
    </section>
    <section class="section">
      <h2>Manual Door Controls</h2>
      <div class="row">
        <button class="btn-secondary" data-endpoint="/Door1Open">Door 1 — OPEN</button>
        <button class="btn-secondary" data-endpoint="/Door1Close">Door 1 — CLOSE</button>
        <button class="btn-secondary" data-endpoint="/Door2Open">Door 2 — OPEN</button>
        <button class="btn-secondary" data-endpoint="/Door2Close">Door 2 — CLOSE</button>
      </div>
      <div class="status"><span class="dot" id="dot-doors"></span><span id="msg-doors" class="small">No actions yet</span></div>
    </section>
    <section class="section">
      <h2>House Lights</h2>
      <div class="row"><button class="btn-secondary" data-endpoint="/ToggleHouseLights">Toggle House Lights</button></div>
      <div class="status"><span class="dot" id="dot-lights"></span><span id="msg-lights" class="small">No actions yet</span></div>
    </section>
    <section class="section">
      <h2>Demo Controls</h2>
      <div class="row">
        <button class="btn-secondary" data-endpoint="/DemoRoom1">Room 1</button>
        <button class="btn-secondary" data-endpoint="/DemoRoom2">Room 2</button>
        <button class="btn-secondary" data-endpoint="/DemoRoom3">Room 3</button>
        <button class="btn-secondary" data-endpoint="/DemoRoom4">Room 4</button>
        <button class="btn-secondary" data-endpoint="/DemoRoom5">Room 5</button>
      </div>
      <div class="status"><span class="dot" id="dot-demo"></span><span id="msg-demo" class="small">No actions yet</span></div>
    </section>
    <footer>Sends simple <span class="kbd">GET /path</span> requests to this server.</footer>
  </main>
  <script>
    async function send(endpoint, section) {
      const buttons = section.querySelectorAll('button');
      buttons.forEach(b => b.disabled = true);
      const dot = section.querySelector('.dot');
      const msg = section.querySelector('[id^="msg-"]');
      try {
        if (navigator.vibrate) navigator.vibrate(10);
        const res = await fetch(endpoint, { method: 'GET', cache: 'no-store' });
        const ok = res.ok;
        dot.classList.remove('err'); dot.classList.add('ok');
        msg.textContent = ok ? `OK → ${endpoint}` : `HTTP ${res.status}`;
      } catch (e) {
        dot.classList.remove('ok'); dot.classList.add('err');
        msg.textContent = `Failed → ${endpoint}`;
      } finally { buttons.forEach(b => b.disabled = false); }
    }
    document.querySelectorAll('button[data-endpoint]').forEach(btn => {
      btn.addEventListener('click', () => {
        const endpoint = btn.dataset.endpoint;
        const section = btn.closest('section');
        if (btn.dataset.confirm === 'true') {
          if (!confirm('Are you sure you want to trigger EMERGENCY SHUTOFF?')) return;
        }
        send(endpoint, section);
      });
    });
  </script>
</body>
</html>'''

# ---------------------------------------------------------------------------
# SERVER HANDLER
# ---------------------------------------------------------------------------
class HalloweenHTTP(BaseHTTPRequestHandler):
    def do_GET(self):
        from control.system import StartHouse
        message = self.path
        log_event(f"[HTTP] Received request: {message}")

        if message == "/":
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(WEBPAGE.encode('utf-8'))
            return

        elif message == "/START":
            threading.Thread(target=StartHouse, daemon=True, name="HOUSE").start()
        elif message == "/EMERGENCY_SHUTOFF":
            house.systemState = "EmergencyShutoff"
        elif message == "/SOFT_SHUTDOWN":
            house.systemState = "SoftShutdown"
        elif message == "/Door1Open":
            setDoorState(1, "OPEN")
        elif message == "/Door1Close":
            setDoorState(1, "CLOSED")
        elif message == "/Door2Open":
            setDoorState(2, "OPEN")
        elif message == "/Door2Close":
            setDoorState(2, "CLOSED")
        elif message == "/ToggleHouseLights":
            toggleHouseLights()
        elif message == "/DemoRoom1":
            demoEvent(Room_1.__name__.split('.')[-1])
        elif message == "/DemoRoom2":
            demoEvent(Room_2.__name__.split('.')[-1])
        elif message == "/DemoRoom3":
            demoEvent(Room_3.__name__.split('.')[-1])
        elif message == "/DemoRoom4":
            demoEvent(Room_4.__name__.split('.')[-1])
        elif message == "/DemoRoom5":
            demoEvent(Room_5.__name__.split('.')[-1])

        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(bytes(f"<html><body><h1>Received {message}</h1></body></html>", "utf-8"))


def HTTP_SERVER():
    log_event(f"[HTTP] Attempting to host server at http://{HOST}:{PORT}")
    server = HTTPServer((HOST, PORT), HalloweenHTTP)
    log_event(f"[HTTP] Server started at http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        log_event("[HTTP] Server stopped.")
