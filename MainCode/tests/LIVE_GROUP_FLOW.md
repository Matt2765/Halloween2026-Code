# Connected room-flow simulation — October 31, 2026

Three groups ran at normal speed with the connected house, actual scene audio,
doors, lights, animatronics, and temporary in-memory sensor/actor inputs.

Verified behavior:

- All three BTN1 presses cancelled an actively playing Pedro quip before the
  Cabin intro. Body idle stayed enabled.
- Basement reservations admitted each group once. Bathroom held Door 4 closed
  when Basement was busy; hallway starts were observed only after Door 4 opened.
- Normal exit released Basement about 18.2 seconds after exit opening.
- Repeated straggler trips held it about 55 seconds. An earlier PIR7 trip did
  not release the following group. The waiting group was admitted at 02:40:11.
- Unknown exit-sensor data reset clearance. The third group cleared after
  about 32.1 seconds, once valid LOW had lasted ten seconds.
- All rooms remained INACTIVE after soft shutdown. Both audio streams reported
  zero callback underruns. Original button readers were restored and no
  simulated device records remained after cleanup.

The external observer missed Group 2's brief ready state because the waiting
group reserved immediately. Its completion was verified from the room's
clear/ready log followed by the accepted Group 3 handoff, rather than inferred
from a later status poll. No simulation assertions failed.

The lantern reached OFF / next cue 14 despite a cue 12 result timeout. It also
reported a later reboot; that hardware/radio issue remains separate from flow.

Runtime inputs and results were kept outside the project:
`C:\Users\minen\AppData\Local\Temp\haunt-flow-live-32sgpva4`.
No fake inputs remain active. The visible PowerShell log window can be closed.

## Configuration

`control/group_flow.py` defines a ten-second continuous clear period and a
15-second minimum exit-lighting period. Exit readiness also requires Door 6
closed (the existing timed estimate, not position feedback). The exit sensor
comes from `control.doors.DOOR_SENSOR_IDS[6]`, currently PIR4. At least one exit
trip is required; missing/warming/stale readings reset the quiet timer. PIR7
is supporting downstream evidence and is never a mandatory trigger.

Only Basement writes its own ACTIVE/STANDBY/INACTIVE state. Bathroom reserves
space and posts an arrival instead. Do not restore cross-room assignments to
`house.Basement_state`.
