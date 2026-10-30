from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from MainCode.rooms import CabinRoom, Bathroom, ShowerHallway, DynamicHallway, Basement, PalletHallway, ForestHallway
from control.doors import setDoorState
from control.houseLights import toggleHouseLights
from utils.tools import log_event
from context import house
from ui.gui import demoEvent
import threading
from control.animatronic_service import start_pedro, stop_pedro

HOST = "0.0.0.0"  # Listen on all interfaces
PORT = 9999

ROOM_STATES = (
    ("CabinRoom", "Cabin Room"), ("Bathroom", "Bathroom"),
    ("ShowerHallway", "Shower Hallway"), ("DynamicHallway", "Dynamic Hallway"),
    ("Basement", "Basement"), ("PalletHallway", "Pallet Hallway"),
    ("ForestHallway", "Forest Hallway"),
)

# ---------------------------------------------------------------------------
# HTML PAGE CONTENT
# ---------------------------------------------------------------------------
WEBPAGE = '''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>Halloween Remote Control</title>
<style>
:root{color-scheme:light;--bg:orange;--panel:#ffb52b;--ink:#171717;--button:#eee;--line:#aa6900}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px Arial,sans-serif}body.dark{color-scheme:dark;--bg:#181818;--panel:#28231b;--ink:#fff0db;--button:#343434;--line:#815a20}header,main,nav{max-width:650px;margin:auto;padding:12px}header{display:flex;justify-content:space-between;align-items:center}h1{font-size:21px;margin:0}h2{font-size:16px;font-weight:500;margin:14px 0 9px}button{font:inherit;color:var(--ink);background:var(--button);border:1px solid var(--line);border-bottom-width:3px;border-radius:5px;min-height:48px;padding:10px;touch-action:manipulation}button:disabled{opacity:.45}button:focus-visible{outline:3px solid #0080ff}nav{display:flex;gap:6px;position:sticky;top:0;background:var(--bg);z-index:2}nav button{flex:1;min-width:0;padding:8px}nav button[aria-selected=true]{background:#171717;color:orange;border-color:orange}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.doors{display:block}.door-row{display:grid;grid-template-columns:1fr 82px;gap:10px;align-items:center;padding:8px 0;border-bottom:1px solid var(--line)}.door-row strong{font-size:15px}.door-row small{font-size:12px;line-height:1.5;margin:2px 0}.door-row button{padding:6px 12px;min-height:40px;font-size:14px}.door-row .bypass{font-weight:bold}.red{background:red;color:white}.cyan{background:cyan;color:black}.yellow{background:yellow;color:black}.green{background:#80ee00;color:black}.card{padding:12px;background:var(--panel);border:1px solid var(--line);border-radius:6px;margin:10px 0}.muted,small{font-size:12px}small{display:block;margin-top:5px}#connection{padding:0 12px;max-width:650px;margin:auto;font-size:13px}#notice{min-height:22px;margin:8px 0;font-size:14px}table{width:100%;border-collapse:collapse;font-size:14px}td,th{text-align:left;padding:9px 4px;border-bottom:1px solid var(--line);overflow-wrap:anywhere}th{font-size:12px}section[hidden]{display:none}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px Arial}footer{padding:12px;text-align:center;font-size:12px}main{padding-top:0}#emergency{width:100%}
nav{overflow-x:auto}nav button{font-size:14px;flex:1 0 auto}select,input{font:inherit;color:var(--ink);background:var(--button);border:1px solid var(--line);border-radius:4px;padding:8px;max-width:100%;min-height:42px}.test-row{padding:12px 0;border-bottom:1px solid var(--line)}.test-controls{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-top:7px}.test-controls button{min-height:42px;padding:7px 13px;font-size:14px}.test-controls input[type=number]{width:82px}.test-result{font-size:12px;min-height:16px;display:block;margin-top:5px}.test-result.error{color:#ad0000}.dark .test-result.error{color:#ffabab}#testRoom{width:100%;margin:10px 0}.test-head{font-weight:bold;font-size:15px}#tests details{margin:12px 0}#tests summary{padding:10px 0}
</style><body><header><h1>HALLOWEEN CONTROL</h1><button id="theme" aria-label="Toggle dark mode">Dark mode</button></header><div id="connection" role="status">Connecting...</div>
<nav aria-label="Control screens"><button data-tab="home" aria-selected="true">Mains</button><button data-tab="sensors">Sensors</button><button data-tab="demos">Demos</button><button data-tab="devices">Devices</button><button data-tab="tests">Test</button></nav>
<main><button class="red" id="emergency" data-action="/EMERGENCY_SHUTOFF">EMERGENCY SHUTOFF</button><div id="notice" role="status" aria-live="polite"></div>
<section id="home"><h2>MAINS</h2><div class="grid"><button class="cyan" data-action="/START">START HOUSE</button><button class="yellow" data-action="/SOFT_SHUTDOWN">SOFT SHUTDOWN</button><button class="green" data-action="/ToggleHouseLights" id="lights">House lights</button><button data-tab="sensors">View all sensors</button></div><h2>DOOR CONTROLS</h2><div class="grid doors" id="doors"></div><details><summary>One-time door overrides</summary><p class="muted">Force close ignores the sensor and clear delay for this movement.</p><div class="grid" id="forceDoors"></div></details><div class="card" id="overview"></div><h2>ROOM STATES</h2><table><thead><tr><th>Room</th><th>State</th></tr></thead><tbody id="roomStates"></tbody></table></section>
<section id="sensors" hidden><h2>SENSORS & BUTTONS</h2><table><thead><tr><th>ID</th><th>TOF</th><th>BUTTON / AGE</th><th>PIR</th></tr></thead><tbody id="sensorRows"></tbody></table><h2>DROPDOWN SENSOR</h2><div class="card" id="dropdownButton">unknown</div><div class="card" id="health"></div></section>
<section id="demos" hidden><h2>ROOM DEMOS</h2><div class="grid" id="demoButtons"></div><h2>PEDRO</h2><div class="grid"><button data-action="/PedroStart">Start Pedro</button><button data-action="/PedroStop">Stop Pedro</button></div><div class="card" id="pedro"></div></section>
<section id="devices" hidden><h2>SERVOS & DROPDOWN</h2><div id="servos"></div><h2>LANTERNS</h2><div id="lanterns"></div><h2>LAST COMMAND FAILURE</h2><pre class="card" id="failure"></pre></section><section id="tests" hidden><h2>OUTPUT TESTS</h2><p class="muted">Test controls also work during house sequences and demos. Running effects may change these outputs again. Values below are test requests; Sensors and Devices show live readings.</p><label for="testRoom">Room or device group</label><select id="testRoom"><option>Loading controls...</option></select><div id="testPanel"></div><details><summary>Unassigned controls</summary><div id="testUnmapped" class="muted"></div></details></section></main>
<script>
const $=id=>document.getElementById(id);let state=null,busy=false,last=0;
function theme(dark){document.body.classList.toggle('dark',dark);$('theme').textContent=dark?'Light mode':'Dark mode';try{localStorage.setItem('haunt-dark',dark)}catch{}}
try{theme(localStorage.getItem('haunt-dark')==='true')}catch{}$('theme').onclick=()=>theme(!document.body.classList.contains('dark'));
for(const room of ['CabinRoom','Bathroom','ShowerHallway','DynamicHallway','Basement','PalletHallway','ForestHallway']){const b=document.createElement('button');b.textContent=room;b.dataset.action='/Demo'+room;$('demoButtons').append(b)}
for(let i=1;i<=6;i++){for(const action of ['Open','Close']){const b=document.createElement('button');b.textContent='Door '+i+' - Force '+action.toLowerCase();b.dataset.action='/ForceDoor'+i+action;$('forceDoors').append(b)}}
function text(id,value){$(id).textContent=value}function card(parent,title,value){const d=document.createElement('div');d.className='card';d.textContent=title+' | '+value;$(parent).append(d)}
function age(ms){return ms==null?'--':(ms/1000).toFixed(1)+'s'}
function renderDropdownButton(reading){const value=reading?.value,status=reading?.status||{};text('dropdownButton',(value===true?'True (pressed)':value===false?'False (released)':'unknown ('+(status.state||'unavailable')+')')+' | '+age(status.age_ms))}
function renderRoomStates(rooms){const rows=[];for(const room of rooms){const row=document.createElement('tr');for(const value of [room.name,room.state]){const cell=document.createElement('td');cell.textContent=value;row.append(cell)}rows.push(row)}$('roomStates').replaceChildren(...rows)}
function render(s){state=s;renderDropdownButton(s.dropdown_button);renderAnimatronicTests(s.animatronics||{});renderRoomStates(s.rooms||[]);text('lights','Lights: '+(s.lights?'ON':'OFF')+' | Toggle');text('overview',s.system+' | House '+(s.active?'active':'idle'));text('pedro','Pedro '+(s.pedro.running?(s.pedro.connected?'running':'waiting for link'):s.pedro.mode==='idle'?'idle animations':'stopped')+' | '+s.pedro.channel+(s.pedro.error?' | '+s.pedro.error:''));$('doors').replaceChildren();for(const d of s.doors){const row=document.createElement('div');row.className='door-row';const info=document.createElement('div');const title=document.createElement('strong');title.textContent='Door '+d.id+' - '+d.state;const detail=document.createElement('small');detail.textContent='Target: '+d.target+' | '+d.sensor+': '+(d.pir?.available?(d.pir.output?'HIGH':'LOW')+(d.pir.ready?' ready':' warming'):d.pir?.state||'unavailable')+(d.bypass?' | BYPASS ACTIVE':'');info.append(title,detail);const button=document.createElement('button');const opening=d.target==='CLOSED'||d.state==='CLOSING';button.dataset.action='/Door'+d.id+(opening?'Open':'Close');button.textContent=opening?'Open':'Close';row.append(info,button);$('doors').append(row)}
$('sensorRows').replaceChildren();for(let i=0;i<6;i++){const p=s.pirs[i],b=s.buttons[i],t=s.tofs[i];const row=document.createElement('tr');for(const v of [i+1,t.value==null?t.status.state:t.value+' mm',(b.value===true?'held':b.value===false?'sleep':'unknown')+' / '+age(b.status.age_ms),p.available?(p.output?'HIGH':'LOW')+(p.ready?' ready':' warming'):p.state]){const td=document.createElement('td');td.textContent=v;row.append(td)}$('sensorRows').append(row)}
text('health',s.health.disabled?'RSM DISABLED':!s.health.connected?'Bridge unavailable':'Bridge connected'+(s.health.error?.message?' | Last USB warning: '+(s.health.error.message==='Oversized USB line'?'Discarded a serial message longer than 1,024 bytes':s.health.error.message):''));text('failure',s.failure?JSON.stringify(s.failure,null,2):'No command failure');
$('servos').replaceChildren();for(const [id,v] of Object.entries(s.servos))card('servos',id,(v.output_angle==null||['stale','unavailable','conflict'].includes(v.state)?v.state:'PWM '+v.output_angle+' deg'+(v.moving?' | moving':''))+' / '+age(v.age_ms));$('lanterns').replaceChildren();for(const [id,v] of Object.entries(s.lanterns))card('lanterns',id,v.available&&v.lantern_state?v.lantern_state.replaceAll('_',' ')+' | '+(v.synced?'wait '+v.next_command_id:'free'):v.state);lock(false)}
function lock(stale){document.querySelectorAll('[data-action],[data-test]' ).forEach(b=>b.disabled=(busy&&b.id!=='emergency')||(stale&&b.id!=='emergency'))}
async function poll(){try{const r=await fetch('/api/status',{cache:'no-store',signal:AbortSignal.timeout(4000)});if(!r.ok)throw Error();render(await r.json());last=Date.now();text('connection','Connected | updated '+new Date().toLocaleTimeString())}catch{text('connection','Disconnected | status is stale | reconnecting...');lock(true)}finally{setTimeout(poll,1000)}}
document.addEventListener('click',async e=>{const b=e.target.closest('button');if(!b)return;if(b._test){await sendTest(b);return}if(b.dataset.tab){for(const id of ['home','sensors','demos','devices','tests'])$(id).hidden=id!==b.dataset.tab;document.querySelectorAll('nav button').forEach(x=>x.setAttribute('aria-selected',x.dataset.tab===b.dataset.tab));return}const endpoint=b.dataset.action;if(!endpoint)return;if(endpoint==='/EMERGENCY_SHUTOFF'&&!confirm('Trigger emergency shutoff?'))return;busy=true;lock(false);text('notice','Sending...');try{const r=await fetch(endpoint,{cache:'no-store',signal:AbortSignal.timeout(8000)});if(!r.ok)throw Error('Server returned '+r.status);text('notice','Command received.')}catch(err){text('notice','No confirmation: command may have run. Check status before retrying.')}finally{busy=false;lock(Date.now()-last>5000)}});lock(true);poll();

let testCatalog=null;
function el(tag,value){const n=document.createElement(tag);if(value!==undefined)n.textContent=value;return n}
function testRow(label,detail){const row=el('div');row.className='test-row';const title=el('div',label);title.className='test-head';row.append(title,el('small',detail));const controls=el('div');controls.className='test-controls';const result=el('output');result.className='test-result';row.append(controls,result);$('testPanel').append(row);return {row,controls,result}}
function testButton(row,label,request){const b=el('button',label);b.dataset.test='true';b._test=request;b._result=row.result;row.controls.append(b);return b}
function numberInput(row,value,min,max,step=1){const n=el('input');n.type='number';Object.assign(n,{value,min,max,step});n.setAttribute('aria-label',row.row.firstChild.textContent+' value');row.controls.append(n);return n}
async function sendTest(b){if(busy)return;const payload=b._test();if(payload===null)return;busy=true;lock(false);b._result.classList.remove('error');b._result.textContent='Sending...';try{const r=await fetch('/api/tests',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),signal:AbortSignal.timeout(8000)});const data=await r.json();if(!r.ok)throw Error(data.error||'Request failed');b._result.textContent=data.message}catch(err){b._result.classList.add('error');b._result.textContent=err.name==='TimeoutError'?'No confirmation. Check output before retrying.':err.message}finally{busy=false;lock(Date.now()-last>5000)}}
function renderAnimatronicTests(characters){for(const [id,v] of Object.entries(characters)){const target=$('animatronic-status-'+id);if(target)target.textContent=(v.connected?'Connected':'Waiting for link')+' | '+(v.mode||'off')+' | '+v.channel+(v.error?' | '+v.error:'')}}
function buildTests(){if(!testCatalog)return;const c=testCatalog,group=$('testRoom').value;$('testPanel').replaceChildren();
for(const item of (c.mosfets||[]).filter(x=>x.room===group)){const row=testRow(item.label,item.node+' | GPIO'+item.pin);for(const value of [true,false])testButton(row,value?'On':'Off',()=>({kind:'mosfet',id:item.id,value}))}
for(const item of c.relays.filter(x=>x.room===group)){const row=testRow(item.label,'Mega D'+item.pin);for(const value of [true,false])testButton(row,value?'On':'Off',()=>({kind:'relay',id:item.id,value}))}
for(const item of c.dimmers.filter(x=>x.room===group)){const row=testRow(item.label,'DIM'+item.id+' | Brightness 0-100%');const n=numberInput(row,0,0,100);testButton(row,'Set %',()=>({kind:'dimmer',id:item.id,value:Number(n.value)}));for(const value of [0,100])testButton(row,value?'Full':'Off',()=>({kind:'dimmer',id:item.id,value}))}
for(const item of c.doors.filter(x=>group==='Doors'||x.room===group)){const row=testRow('Door '+item.id,'Mapped sensor: '+item.sensor);for(const value of ['OPEN','CLOSED'])testButton(row,value==='OPEN'?'Open':'Close',()=>({kind:'door',id:item.id,value}));for(const value of ['OPEN','CLOSED'])testButton(row,value==='OPEN'?'Force open':'Force close',()=>({kind:'door',id:item.id,value,force:true}))}
if(group==='Servos & dropdown'){for(const id of c.servos){const row=testRow(id,'PWM angle 0-180 degrees');const n=numberInput(row,90,0,180);testButton(row,'Set angle',()=>({kind:'servo',id,value:Number(n.value)}))}const row=testRow('Dropdown indicator','DROPDOWN1');for(const value of [true,false])testButton(row,value?'On':'Off',()=>({kind:'led',id:'DROPDOWN1',value}))}
if(group==='Lanterns')for(const id of c.lanterns){const row=testRow(id,'Sends the next numbered cue; device must be synced');const select=el('select');select.setAttribute('aria-label',id+' mode');for(const mode of c.lantern_modes){const option=el('option',mode.replaceAll('_',' '));option.value=mode;select.append(option)}row.controls.append(select);testButton(row,'Apply',()=>({kind:'lantern',id,value:select.value}))}
if(group==='Speakers'){const row=testRow('Speaker test',c.audio_disabled?'Audio disabled in house_state.py':'Speak the selected route name');const select=el('select');select.setAttribute('aria-label','Speaker route');for(const id of c.speakers){const option=el('option',id);option.value=id;select.append(option)}row.controls.append(select);const gain=numberInput(row,0.2,0,1,0.05);testButton(row,'Speak',()=>({kind:'audio',id:select.value,value:'speak',gain:Number(gain.value)}));testButton(row,'Stop audio',()=>({kind:'audio',value:'stop'}))}
if(group==='Animatronics')for(const item of c.animatronics){
const row=testRow(item.name,"Start a talking show or play one quip. Manual controls stop this character and hold the requested pose.");
const status=el('div');status.id='animatronic-status-'+item.id;status.className='muted';status.setAttribute('role','status');row.row.insertBefore(status,row.controls);
const route=el('select');route.setAttribute('aria-label',item.name+' speaker route');for(const id of c.speakers){const option=el('option',id);option.value=id;route.append(option)}route.value=item.name;row.controls.append(route);
const gain=numberInput(row,1,0,1,0.05);gain.setAttribute('aria-label',item.name+' voice gain');
for(const [value,label] of [['start','Start talking'],['talk','Play one quip'],['stop','Stop & park']])testButton(row,label,()=>({kind:'animatronic',id:item.id,value,channel:route.value,gain:Number(gain.value)}));
for(const [value,label] of [['idle_start','Start idle'],['idle_stop','Stop idle']])testButton(row,label,()=>({kind:'animatronic',id:item.id,value}));
for(const output of item.outputs){const controls=testRow(item.name+' '+output.label,output.type==='angle'?'Servo angle '+output.min+'-'+output.max+' degrees':'Digital output');
if(output.type==='digital'){for(const value of [true,false])testButton(controls,value?'On':'Off',()=>({kind:'animatronic',id:item.id,value:'pose',outputs:{[output.id]:value}}))}
else{const angle=numberInput(controls,output.rest,output.min,output.max);angle.setAttribute('aria-label',item.name+' '+output.label+' angle');testButton(controls,'Set angle',()=>({kind:'animatronic',id:item.id,value:'pose',outputs:{[output.id]:Number(angle.value)}}));for(const [label,value] of [['Min',output.min],['Max',output.max],['Rest',output.rest]])testButton(controls,label,()=>{angle.value=value;return {kind:'animatronic',id:item.id,value:'pose',outputs:{[output.id]:value}}})}}
}renderAnimatronicTests(state?.animatronics||{});
for(const item of (c.unassigned||[]).filter(x=>x.room===group)){const row=testRow(item.label,item.detail);row.result.textContent='Not configured';for(const label of ['On','Off']){const b=el('button',label);b.disabled=true;row.controls.append(b)}}
if(!$('testPanel').children.length)$('testPanel').append(el('p','No assigned controls for this room yet. See Unassigned controls.'));lock(Date.now()-last>5000)}
async function loadTests(){try{const r=await fetch('/api/tests',{cache:'no-store'});if(!r.ok)throw Error('Could not load controls');testCatalog=await r.json();const rooms=[...new Set([...testCatalog.relays,...testCatalog.dimmers,...(testCatalog.mosfets||[]),...(testCatalog.unassigned||[])].map(x=>x.room))];rooms.push('Doors','Servos & dropdown','Lanterns','Speakers','Animatronics');$('testRoom').replaceChildren();for(const room of rooms){const o=el('option',room);o.value=room;$('testRoom').append(o)}$('testUnmapped').replaceChildren(...testCatalog.unmapped.map(x=>el('p',x)));buildTests()}catch(err){$('testPanel').textContent=err.message+'; refresh to retry'}}
$('testRoom').onchange=buildTests;loadTests();
</script></body></html>'''

# ---------------------------------------------------------------------------
# SERVER HANDLER
# ---------------------------------------------------------------------------
class HalloweenHTTP(BaseHTTPRequestHandler):
    # Bound waits for idle/incomplete requests and stalled response readers.
    timeout = 10

    def log_request(self, code="-", size="-"):
        # Live polling is expected traffic, not an operational event.
        if self.path == "/api/status" and str(code) == "200":
            return
        super().log_request(code, size)

    def handle(self):
        try:
            # Detect a TLS ClientHello before the HTTP parser waits for a newline
            # or dumps binary handshake data as a malformed HTTP request.
            if self.rfile.peek(1)[:1] == b'\x16':
                address, port = self.connection.getsockname()[:2]
                log_event(f"[HTTP] HTTPS attempted by {self.client_address[0]}; "
                          f"open http://{address}:{port}/ explicitly. "
                          "This port does not support HTTPS.")
                self.close_connection = True
                return
            super().handle()
        except TimeoutError:
            self.close_connection = True
            if house.DEBUG_INFO:
                log_event(f"[HTTP] Idle client timed out: {self.client_address}")
        except (ConnectionResetError, BrokenPipeError):
            # Browsers may close idle connections or leave before a response.
            self.close_connection = True
            if house.DEBUG_INFO:
                log_event(f"[HTTP] Client disconnected: {self.client_address}")

    def _json(self, status, data):
        import json
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        import json
        if self.path != "/api/tests":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                raise ValueError("Invalid request length")
            request = json.loads(self.rfile.read(length))
            from control.web_tests import execute
            result = execute(request)
        except (ValueError, TypeError) as error:
            self._json(400, {"error": str(error)})
        except RuntimeError as error:
            self._json(409, {"error": str(error)})
        except Exception as error:
            log_event(f"[Test] Command failed: {error}")
            self._json(500, {"error": "Test command failed; check system log"})
        else:
            self._json(200, result)

    def do_GET(self):
        if self.path == "/api/tests":
            from control.web_tests import catalog
            self._json(200, catalog())
            return
        if self.path == "/api/status":
            import json
            payload = json.dumps(status_snapshot()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        message = self.path
        log_event(f"[HTTP] Received request: {message}")

        if message == "/":
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(WEBPAGE.encode('utf-8'))
            return

        elif message == "/START":
            from control.system import StartHouse
            threading.Thread(target=StartHouse, daemon=True, name="HOUSE").start()
        elif message == "/PedroStart":
            if not start_pedro():
                self.send_response(503)
                self.end_headers()
                self.wfile.write(b"Pedro could not start; check the main system log.")
                return
        elif message == "/PedroStop":
            threading.Thread(target=stop_pedro, daemon=True, name="Pedro stop").start()
        elif message == "/EMERGENCY_SHUTOFF":
            house.systemState = "EmergencyShutoff"
        elif message == "/SOFT_SHUTDOWN":
            house.systemState = "SoftShutdown"
        elif message.startswith("/ForceDoor"):
            from control.doors import DOOR_SOLENOID_PINS
            commands = {f"/ForceDoor{i}{action}": (i, state)
                        for i in DOOR_SOLENOID_PINS
                        for action, state in (("Open", "OPEN"), ("Close", "CLOSED"))}
            if message not in commands:
                self.send_error(404)
                return
            if house.systemState != "ONLINE":
                self.send_error(409, "Door overrides require the system to be ONLINE")
                return
            door, state = commands[message]
            setDoorState(door, state, bypass_sensor=True)
        elif message == "/Door1Open":
            setDoorState(1, "OPEN")
        elif message == "/Door1Close":
            setDoorState(1, "CLOSED")
        elif message == "/Door2Open":
            setDoorState(2, "OPEN")
        elif message == "/Door2Close":
            setDoorState(2, "CLOSED")
        elif message == "/Door3Open":
            setDoorState(3, "OPEN")
        elif message == "/Door3Close":
            setDoorState(3, "CLOSED")
        elif message == "/Door4Open":
            setDoorState(4, "OPEN")
        elif message == "/Door4Close":
            setDoorState(4, "CLOSED")
        elif message == "/Door5Open":
            setDoorState(5, "OPEN")
        elif message == "/Door5Close":
            setDoorState(5, "CLOSED")
        elif message == "/Door6Open":
            setDoorState(6, "OPEN")
        elif message == "/Door6Close":
            setDoorState(6, "CLOSED")
        elif message == "/ToggleHouseLights":
            toggleHouseLights()
        elif message == "/DemoCabinRoom":
            demoEvent(CabinRoom.__name__.split('.')[-1])
        elif message == "/DemoBathroom":
            demoEvent(Bathroom.__name__.split('.')[-1])
        elif message == "/DemoShowerHallway":
            demoEvent(ShowerHallway.__name__.split('.')[-1])
        elif message == "/DemoDynamicHallway":
            demoEvent(DynamicHallway.__name__.split('.')[-1])
        elif message == "/DemoBasement":
            demoEvent(Basement.__name__.split('.')[-1])
        elif message == "/DemoPalletHallway":
            demoEvent(PalletHallway.__name__.split('.')[-1])
        elif message == "/DemoForestHallway":
            demoEvent(ForestHallway.__name__.split('.')[-1])

        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(bytes(f"<html><body><h1>Received {message}</h1></body></html>", "utf-8"))


def status_snapshot():
    from control import remote_sensor_monitor as rsm
    from control.doors import DOOR_SOLENOID_PINS, DOOR_SENSOR_IDS, DOOR_SENSOR_BYPASS
    from control.animatronic_service import pedro_status, george_status
    dropdown_status = rsm.device_status("DROPDOWN1")
    dropdown_value = rsm.get_button_value("DROPDOWN1") if dropdown_status.get("available") else None
    return {
        "system": house.systemState, "active": house.HouseActive,
        "lights": house.houseLights, "pedro": pedro_status(),
        "animatronics": {"pedro": pedro_status(), "george": george_status()},
        "rooms": [{"id": room, "name": label,
                   "state": getattr(house, f"{room}_state", "UNKNOWN")}
                  for room, label in ROOM_STATES],
        "doors": [{"id": i, "state": house.DoorState.get(i, "UNKNOWN"),
                   "target": house.TargetDoorState.get(i, "UNKNOWN"),
                   "bypass": DOOR_SENSOR_BYPASS.get(i, False),
                   "pir": rsm.get_pir_state(DOOR_SENSOR_IDS[i]),
                   "sensor": DOOR_SENSOR_IDS.get(i, "unmapped")}
                  for i in DOOR_SOLENOID_PINS],
        "tofs": [{"value": rsm.get_value(f"TOF{i}", "dist_mm"),
                  "status": rsm.device_status(f"TOF{i}")} for i in range(1, 7)],
        "buttons": [{"value": rsm.get_button_value(f"BTN{i}"),
                     "status": rsm.device_status(f"BTN{i}")} for i in range(1, 7)],
        "dropdown_button": {"value": dropdown_value, "status": dropdown_status},
        "pirs": [rsm.get_pir_state(f"PIR{i}") for i in range(1, 7)],
        "servos": {i: rsm.get_servo_state(i) for i in ("DROPDOWN1", "SERVO1", "SERVO2")},
        "lanterns": {f"LANTERN{i}": rsm.get_lantern_state(f"LANTERN{i}") for i in range(1, 5)},
        "health": rsm.healthy(), "failure": rsm.command_failure(),
    }


def HTTP_SERVER():
    log_event(f"[HTTP] Attempting to host server at http://{HOST}:{PORT}")
    # Browsers pre-open sockets; one idle socket must not block other clients.
    server = ThreadingHTTPServer((HOST, PORT), HalloweenHTTP)
    log_event(f"[HTTP] Server started at http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        log_event("[HTTP] Server stopped.")
