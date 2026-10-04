#include <HauntProtocol.h>
#include <ArduinoJson.h>
#include <new>
using namespace haunt;
// ===== PER-FLASH DEVICE CONFIGURATION =====
// One PC bridge per network. Its logical ID is shared BRIDGE_ID.
constexpr uint32_t HEARTBEAT_MS = 1000, HOST_TIMEOUT_MS = 1500;
// Channel, network, USB baud and retries: HauntConfig.h
// ========================================
Radio radio;
constexpr size_t LINE_SIZE=768;
struct Line { char text[LINE_SIZE]={}; uint32_t created=0; };
// Allocate fixed-capacity storage on the heap; ESP32's static DRAM segment is small.
Line *critical=nullptr,*periodic=nullptr,writing;
uint8_t head=0,count=0,scan=0;
size_t writeOffset=0;
uint32_t outputDrops=0,outputHighWater=0,lastHeartbeat=0,hostSeen=0;
char host[33]={};
struct Request { bool used=false; uint32_t seq=0; char cid[33]={}; };
Request requests[MAX_PENDING];
const char* codeName(Code c) {
  switch(c) {
    case ACCEPTED:return "accepted"; case SUPERSEDED:return "superseded";
    case UNCONFIRMED:return "unconfirmed"; default:return "rejected";
  }
}
const char* reason(Code c) {
  switch(c) {
    case ACCEPTED:return "accepted_by_recipient"; case INVALID:return "invalid_command";
    case SUPERSEDED:return "newer_command"; case WRONG_SESSION:return "device_restarted";
    case CONFLICT:return "id_conflict"; case QUEUE_FULL:return "queue_full"; default:return "ack_not_received";
  }
}
bool queueLine(JsonDocument& doc,bool urgent,int slot=64,bool event=false) {
  doc["v"]=VERSION;
  if(doc.overflowed() || measureJson(doc)+32>LINE_SIZE) { outputDrops++; return false; }
  Line* line;
  if(urgent) {
    // Reserve enough slots for every outstanding command result and USB error.
    if(count>=(event?48:80)) { outputDrops++; return false; }
    line=&critical[(head+count)%80]; count++;
    if(count>outputHighWater) outputHighWater=count;
  } else line=&periodic[slot];
  line->created=doc["rx_ms"] | millis(); // Include time spent in the radio callback queue.
  size_t n=serializeJson(doc,line->text,LINE_SIZE-2); line->text[n++]='\n'; line->text[n]=0;
  return true;
}
void writeTick() {
  // Keep snapshots replaceable until the UART can actually start a line.
  if(Serial.availableForWrite()<=0) return;
  if(!writing.text[0]) {
    if(count) { writing=critical[head]; head=(head+1)%80; count--; }
    else {
      // USB heartbeat gets first opportunity, even during sustained telemetry.
      if(periodic[64].text[0]) { writing=periodic[64]; periodic[64].text[0]=0; }
      else for(int i=0;i<64;i++) {
        uint8_t n=scan++%64;
        if(periodic[n].text[0]) { writing=periodic[n]; periodic[n].text[0]=0; break; }
      }
    }
    writeOffset=0;
    if(writing.text[0]) {
      StaticJsonDocument<1024> doc;
      // Copy strings: zero-copy parsing would alias the buffer being overwritten.
      deserializeJson(doc,static_cast<const char*>(writing.text));
      doc["queue_ms"]=millis()-writing.created;
      size_t n=serializeJson(doc,writing.text,LINE_SIZE-2); writing.text[n++]='\n'; writing.text[n]=0;
    }
  }
  if(!writing.text[0]) return;
  size_t remaining=strlen(writing.text)-writeOffset;
  int room=Serial.availableForWrite();
  if(room>0) writeOffset+=Serial.write(reinterpret_cast<const uint8_t*>(writing.text)+writeOffset,min(remaining,size_t(room)));
  if(!writing.text[writeOffset]) writing.text[0]=0;
}
void resultLine(const char* cid,const char* id,const char* status,const char* detail,uint32_t seq=0,uint32_t elapsed=0,bool acknowledged=false) {
  StaticJsonDocument<512> doc;
  doc["type"]="command_result"; doc["command_id"]=cid; doc["id"]=id;
  doc["status"]=status; doc["reason"]=detail; doc["session"]=radio.session; doc["seq"]=seq; doc["elapsed_ms"]=elapsed;
  if(acknowledged) doc["rtt_ms"]=elapsed; else doc["rtt_ms"]=nullptr;
  queueLine(doc,true);
}
void delivery(const Packet& p,Code code,uint32_t rtt) {
  for(auto& request:requests) if(request.used&&request.seq==p.seq) {
    resultLine(request.cid,p.dst,codeName(code),reason(code),p.seq,rtt,code==ACCEPTED||code==INVALID||code==WRONG_SESSION); request.used=false; return;
  }
}
Code received(const Received& r) {
  const Packet& p=r.packet;
  auto peer=radio.registry.find(p.src);
  if(!peer) return QUEUE_FULL;
  int slot=int(peer-radio.registry.peers);
  if(peer->conflict) {
    radio.cancel(p.src,CONFLICT);
    StaticJsonDocument<256> doc;
    doc["type"]="diagnostic"; doc["id"]=p.src; doc["error"]="id_conflict";
    queueLine(doc,false,slot); return CONFLICT;
  }
  if(p.type==COMMAND) return INVALID;
  StaticJsonDocument<1024> doc;
  doc["type"]=p.type==DIAGNOSTIC?"diagnostic":"device";
  doc["id"]=p.src; doc["session"]=p.session; doc["seq"]=p.seq; doc["fw"]=FIRMWARE;
  char mac[18]; snprintf(mac,sizeof(mac),"%02X:%02X:%02X:%02X:%02X:%02X",r.mac[0],r.mac[1],r.mac[2],r.mac[3],r.mac[4],r.mac[5]); doc["mac"]=mac;
  doc["rx_ms"]=r.rxMs; doc["event"]=bool(p.flags) && p.type!=TOF; doc["sequence_gaps"]=peer->gaps;
  auto vals=doc.createNestedObject("vals"); const auto b=p.payload;
  switch(p.type) {
    case TOF:
      doc["kind"]="tof"; vals["valid"]=bool(b[0]); vals["status"]=int16_t(get16(b+3));
      if(b[0]) vals["dist_mm"]=int16_t(get16(b+1)); else vals["dist_mm"]=nullptr;
      vals["ready"]=int16_t(get16(b+3))!=-3; break;
    case BUTTON:doc["kind"]="button"; vals["btn"]=b[0]; vals["pressed"]=bool(b[1]); vals["ready"]=true; break;
    case PIR:doc["kind"]="pir"; vals["output"]=bool(b[0]); vals["ready"]=bool(b[1]); break;
    case SERVO:
      doc["kind"]="servo"; vals["output_angle"]=get16(b); vals["angle"]=get16(b); vals["target"]=get16(b+2);
      vals["moving"]=bool(b[4]); vals["us"]=get16(b+5); vals["command_session"]=get32(b+7); vals["command_seq"]=get32(b+11);
      if(get16(b+15)==0xffff) vals["measured_angle"]=nullptr; else vals["measured_angle"]=get16(b+15);
      vals["ready"]=true; break;
    case SPRITE:
      doc["kind"]="sprite"; vals["index"]=b[0]; vals["command_session"]=get32(b+1); vals["command_seq"]=get32(b+5);
      vals["playback_confirmed"]=false; vals["serial_issued"]=true; vals["ready"]=true; break;
    case LANTERN: {
      const char* states[]={"off","solid_on","flickering_on","intense_flickering_on","flicker_out","intense_flicker_out","strobe"};
      doc["kind"]="lantern"; vals["lantern_state"]=states[b[0]];
      vals["synced"]=bool(b[1]); vals["brightness"]=b[2];
      vals["next_command_id"]=get32(b+3); vals["sync_generation"]=get32(b+7);
      vals["command_session"]=get32(b+11); vals["command_seq"]=get32(b+15);
      vals["ready"]=true; break;
    }
    case DIAGNOSTIC: {
      const char* keys[]={"drops","high_water","retries","unconfirmed","duplicates","send_errors"};
      for(int i=0;i<6;i++) vals[keys[i]]=get32(b+i*4);
      // Diagnostics must not replace the current device state/heartbeat.
      return queueLine(doc,true,slot,true)?ACCEPTED:QUEUE_FULL;
    }
    default:return INVALID;
  }
  // Accepted transitions enter the nonreplaceable USB queue before Radio ACKs.
  // Periodic records replace older periodic records for this device only.
  return queueLine(doc,p.type!=TOF && (p.flags || p.type==BUTTON),slot,true)?ACCEPTED:QUEUE_FULL;
}
void usbLine(const char* line) {
  StaticJsonDocument<640> doc;
  if(deserializeJson(doc,line)||!doc.is<JsonObject>()||doc["v"]!=VERSION) {
    resultLine("","","rejected","protocol_error"); return;
  }
  const char* type=doc["type"]|"";
  const char* token=doc["host"]|"";
  if(!strcmp(type,"hello") && strlen(token)==32) {
    if(strcmp(host,token)) { radio.cancel(nullptr,UNCONFIRMED); strcpy(host,token); }
    hostSeen=millis();
    StaticJsonDocument<256> reply; reply["type"]="hello"; reply["host"]=host; reply["session"]=radio.session; queueLine(reply,true); return;
  }
  if(!strcmp(type,"host_heartbeat") && host[0]&&!strcmp(host,token)) { hostSeen=millis(); return; }
  const char* cid=doc["command_id"]|""; const char* id=doc["id"]|"";
  if(strcmp(type,"command")||strlen(cid)!=32||!validId(id)||!host[0]||strcmp(host,token)||millis()-hostSeen>HOST_TIMEOUT_MS) {
    resultLine(cid,id,"rejected","invalid_request_or_host_session"); return;
  }
  auto peer=radio.registry.find(id);
  if(!peer||peer->conflict||millis()-peer->heard>6000||!doc["target_session"].is<uint32_t>()||doc["target_session"].as<uint32_t>()!=peer->session) {
    resultLine(cid,id,"rejected","unavailable_conflict_or_restarted"); return;
  }
  const char* op=doc["op"]|""; uint8_t operation=0;
  if(!strcmp(op,"move")) operation=MOVE;
  if(!strcmp(op,"set_default")) operation=SET_DEFAULT;
  if(!strcmp(op,"play")) operation=PLAY;
  if(!strcmp(op,"next")) operation=NEXT;
  if(!strcmp(op,"lantern")) operation=LANTERN_STATE;
  if(!operation||!doc["value"].is<uint16_t>()||!doc["duration_ms"].is<uint32_t>()) {
    resultLine(cid,id,"rejected","invalid_command"); return;
  }
  uint16_t value=doc["value"]; uint32_t duration=doc["duration_ms"];
  if((operation!=LANTERN_STATE && duration>30000) || ((operation==MOVE||operation==SET_DEFAULT)&&value>180) || (operation==PLAY&&value>200) ||
     (operation==LANTERN_STATE && (value>LANTERN_STATE_MAX || duration<1 || duration==0xffffffff || !doc["sync_generation"].is<uint32_t>()))) {
    resultLine(cid,id,"rejected","out_of_range"); return;
  }
  if(operation==MOVE||operation==SET_DEFAULT) radio.cancel(id,SUPERSEDED);
  Request* request=nullptr;
  for(auto& r:requests) if(!r.used) { request=&r; break; }
  if(!request) { resultLine(cid,id,"rejected","queue_full"); return; }
  auto p=radio.make(COMMAND,id,operation==LANTERN_STATE?15:11,true); put32(p.payload,peer->session); p.payload[4]=operation;
  put16(p.payload+5,value); put32(p.payload+7,duration);
  if(operation==LANTERN_STATE) put32(p.payload+11,doc["sync_generation"].as<uint32_t>());
  if(!radio.send(p)) { resultLine(cid,id,"rejected","queue_full"); return; }
  request->used=true; request->seq=p.seq; strcpy(request->cid,cid);
  resultLine(cid,id,"pending","bridge_retry_owner",p.seq);
}
void readTick() {
  static char input[512]; static size_t used=0; static bool discard=false;
  // Leave result capacity available if USB output is stalled.
  for(int i=0;i<128 && Serial.available()&&count<32;i++) {
    char c=Serial.read();
    if(c=='\n') {
      if(discard) resultLine("","","rejected","serial_line_too_long");
      else { input[used]=0; usbLine(input); }
      used=0; discard=false; break;
    }
    if(!discard) {
      if(used>=sizeof(input)-1) { used=0; discard=true; }
      else input[used++]=c;
    }
  }
}
void heartbeat() {
  StaticJsonDocument<640> doc;
  doc["type"]="bridge"; doc["id"]=BRIDGE_ID; doc["session"]=radio.session; doc["fw"]=FIRMWARE; doc["ready"]=true;
  auto d=doc.createNestedObject("diagnostics");
  d["rx_drops"]=radio.stats.drops; d["rx_high_water"]=radio.stats.highWater;
  d["usb_drops"]=outputDrops; d["usb_high_water"]=outputHighWater;
  d["retries"]=radio.stats.retries; d["unconfirmed"]=radio.stats.unconfirmed;
  d["duplicates"]=radio.stats.duplicates; d["malformed"]=radio.stats.malformed;
  d["send_errors"]=radio.stats.sendErrors; d["sequence_gaps"]=radio.stats.gaps; d["conflicts"]=radio.stats.conflicts;
  queueLine(doc,false);
}
void setup() {
  Serial.begin(USB_BAUD);
  critical=new(std::nothrow) Line[80]; periodic=new(std::nothrow) Line[65];
  if(!critical||!periodic) { delay(1000); ESP.restart(); }
  if(!radio.begin(BRIDGE_ID,received,delivery)) { delay(1000); ESP.restart(); }
  heartbeat();
}
void loop() {
  readTick();
  if(host[0]&&millis()-hostSeen>HOST_TIMEOUT_MS) { radio.cancel(nullptr,UNCONFIRMED); host[0]=0; }
  radio.poll(); writeTick();
  if(millis()-lastHeartbeat>=HEARTBEAT_MS) { lastHeartbeat=millis(); heartbeat(); }
  delay(1);
}
