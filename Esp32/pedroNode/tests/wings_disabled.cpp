#include "../pedroNode.ino"
#include <cassert>
#include <cstdio>
int main() {
 setup();assert(!WINGS_ENABLED && levels[WINGS_PIN]==LOW && duties[LEDC_CHANNEL_0]==0);
 Received r;auto& p=r.packet;p.type=COMMAND;p.flags=ACK_REQUIRED;p.length=17;
 strcpy(p.src,"BRIDGE");strcpy(p.dst,"PEDRO1");p.session=2;p.seq=3;
 put32(p.payload,1);p.payload[4]=PEDRO_POSE;put16(p.payload+5,ACTIVE);
 put16(p.payload+11,115);put16(p.payload+13,10);p.payload[15]=p.payload[16]=1;
 assert(command(r)==ACCEPTED);
 assert(levels[WINGS_PIN]==LOW && duties[LEDC_CHANNEL_0]==0 && usToAngle(wings.target)==WINGS_REST);
 assert(neck && eyes && usToAngle(beak.target)==10 && duties[LEDC_CHANNEL_1]>0);
 fakeNow=500;loop();assert(levels[WINGS_PIN]==LOW && duties[LEDC_CHANNEL_0]==0);
 fakeNow=3000;controllerTick(fakeNow);
 assert(state==OFF && levels[WINGS_PIN]==LOW && duties[LEDC_CHANNEL_0]==0);
 puts("Pedro disabled wings stay LOW; beak, neck, eyes and failsafe still work");
}
