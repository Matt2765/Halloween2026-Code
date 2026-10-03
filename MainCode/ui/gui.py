# ui/gui.py
import tkinter as tk
import threading
from MainCode.rooms import Room_1, Room_2, Room_3, Room_4, Room_5
from context import house
from control.shutdown import shutdown
from control.doors import setDoorState
from control.houseLights import toggleHouseLights
from utils.tools import log_event

# NEW: read-only sensor values
from control import remote_sensor_monitor as rsm  # minimal addition


def demoEvent(room):
    house.Demo = True
    house.HouseActive = True
    toggleHouseLights(False)
    log_event(f"[GUI] Starting demo of {room}")

    if room == Room_1.__name__.split('.')[-1]:
        threading.Thread(target=Room_1.run, args=(), name=f"{room} demo").start()
    elif room == Room_2.__name__.split('.')[-1]:
        threading.Thread(target=Room_2.run, args=(), name=f"{room} demo").start()
    elif room == Room_3.__name__.split('.')[-1]:
        threading.Thread(target=Room_3.run, args=(), name=f"{room} demo").start()
    elif room == Room_4.__name__.split('.')[-1]:
        threading.Thread(target=Room_4.run, args=(), name=f"{room} demo").start()
    elif room == Room_5.__name__.split('.')[-1]:
        threading.Thread(target=Room_5.run, args=(), name=f"{room} demo").start()


def change_system_state(new_state):
    house.systemState = new_state


def MainGUI():
    from control.system import StartHouse
    log_event(f"[GUI] Booting main GUI...")

    root = tk.Tk()
    root.configure(background="orange")
    root.title("Halloween [year] Control Panel")
    root.geometry("465x1080")

    tk.Label(root, text="MAINS", font=("Helvetica bold", 15), bg="orange").place(x=25, y=15)
    tk.Label(root, text="DOOR CONTROLS", font=("Helvetica bold", 15), bg="orange").place(x=25, y=200)
    tk.Label(root, text="DEMO CONTROLS", font=("Helvetica bold", 15), bg="orange").place(x=25, y=395)

    tk.Button(root, text="START HAUNTED HOUSE", height=3, width=25, bg="turquoise1",
              command=lambda: threading.Thread(target=StartHouse, daemon=True, name="HOUSE").start()).place(x=250, y=50)
    tk.Button(root, text="EMERGENCY SHUTOFF", height=3, width=25, bg="red",
              command=lambda: change_system_state("EmergencyShutoff")).place(x=25, y=50)
    tk.Button(root, text="SOFT SHUTDOWN", height=3, width=25, bg="yellow",
              command=lambda: change_system_state("SoftShutdown")).place(x=25, y=125)

    tk.Button(root, text="Open Door 1", height=2, width=15,
              command=lambda: setDoorState(1, "OPEN")).place(x=25, y=235)
    tk.Button(root, text="Close Door 1", height=2, width=15,
              command=lambda: setDoorState(1, "CLOSED")).place(x=150, y=235)
    tk.Button(root, text="Open Door 2", height=2, width=15,
              command=lambda: setDoorState(2, "OPEN")).place(x=25, y=285)
    tk.Button(root, text="Close Door 2", height=2, width=15,
              command=lambda: setDoorState(2, "CLOSED")).place(x=150, y=285)

    # DEMO CONTROLS (strip "rooms." prefix)
    tk.Button(root, text=f"Demo {Room_1.__name__.split('.')[-1]}", height=2, width=15,
              command=lambda: demoEvent(Room_1.__name__.split('.')[-1])).place(x=150, y=430)
    tk.Button(root, text=f"Demo {Room_3.__name__.split('.')[-1]}", height=2, width=15,
              command=lambda: demoEvent(Room_3.__name__.split('.')[-1])).place(x=25, y=430)
    tk.Button(root, text=f"Demo {Room_5.__name__.split('.')[-1]}", height=2, width=15,
              command=lambda: demoEvent(Room_5.__name__.split('.')[-1])).place(x=275, y=430)
    tk.Button(root, text=f"Demo {Room_2.__name__.split('.')[-1]}", height=2, width=15,
              command=lambda: demoEvent(Room_2.__name__.split('.')[-1])).place(x=25, y=480)
    tk.Button(root, text=f"Demo {Room_4.__name__.split('.')[-1]}", height=2, width=15,
              command=lambda: demoEvent(Room_4.__name__.split('.')[-1])).place(x=150, y=480)

    tk.Button(root, text="Toggle House Lights", height=3, width=25, bg="chartreuse2",
              command=toggleHouseLights).place(x=250, y=125)

    # -------------------------------------------------------------------------
    # NEW: SENSOR + BUTTON STATUS PANEL (fits 465px width)
    # -------------------------------------------------------------------------
    SECTION_Y = 535
    tk.Label(root, text="SENSORS & BUTTONS", font=("Helvetica bold", 15), bg="orange").place(x=25, y=SECTION_Y)

    panel = tk.Frame(root, bg="orange")
    panel.place(x=25, y=SECTION_Y + 30, width=415)  # <= keep within window

    small = ("Helvetica", 11)

    # ===== Row group 1: TOF (left) + Buttons (right) =====
    row1 = tk.Frame(panel, bg="orange")
    row1.grid(row=0, column=0, sticky="nw")

    # TOF table
    tof_frame = tk.Frame(row1, bg="orange")
    tof_frame.grid(row=0, column=0, sticky="nw", padx=(0, 14))
    tk.Label(tof_frame, text="TOF", font=small, bg="orange").grid(row=0, column=0, sticky="w", padx=(0, 10))
    tk.Label(tof_frame, text="Dist", font=small, bg="orange").grid(row=0, column=1, sticky="w")

    tof_ids = ["TOF1", "TOF2", "TOF3", "TOF4", "TOF5"]
    tof_labels = {}
    for i, sid in enumerate(tof_ids, start=1):
        tk.Label(tof_frame, text=sid, font=small, bg="orange").grid(row=i, column=0, sticky="w", padx=(0, 10))
        lbl = tk.Label(tof_frame, text="unavailable", font=small, bg="orange")
        lbl.grid(row=i, column=1, sticky="w")
        tof_labels[sid] = lbl

    # Buttons table
    btn_frame = tk.Frame(row1, bg="orange")
    btn_frame.grid(row=0, column=1, sticky="nw")
    tk.Label(btn_frame, text="Buttons", font=small, bg="orange").grid(row=0, column=0, columnspan=2, sticky="w")

    btn_ids = ["BTN1", "BTN2", "BTN3", "BTN4"]
    btn_labels = {}
    for i, sid in enumerate(btn_ids, start=1):
        tk.Label(btn_frame, text=sid, font=small, bg="orange").grid(row=i, column=0, sticky="w", padx=(0, 6))
        lbl = tk.Label(btn_frame, text="?", font=small, bg="orange")
        lbl.grid(row=i, column=1, sticky="w")
        btn_labels[sid] = lbl

    # ===== Row group 2: Multi Panel (single compact row) =====
    mid = tk.Frame(panel, bg="orange")
    mid.grid(row=1, column=0, sticky="nw", pady=(4, 0))

    tk.Label(mid, text="Multi Panel", font=small, bg="orange").grid(row=0, column=0, columnspan=8, sticky="w")
    multi_id = "Multi_BTN1"
    multi_labels = []
    for i in range(4):
        tk.Label(mid, text=f"B{i+1}", font=small, bg="orange").grid(row=1, column=i*2, sticky="w", padx=(0, 4))
        v = tk.Label(mid, text="?", font=small, bg="orange")
        v.grid(row=1, column=i*2+1, sticky="w", padx=(0, 10))
        multi_labels.append(v)

    # ===== Row group 3: SERVOS (full-width, under Multi) =====
    right = tk.Frame(panel, bg="orange")
    right.grid(row=2, column=0, sticky="nw", pady=(6, 0))

    tk.Label(right, text="SERVOS", font=("Helvetica bold", 13), bg="orange").grid(row=0, column=0, columnspan=2, sticky="w")

    servo_ids = ["SERVO1", "SERVO2"]  # edit as needed
    servo_labels = {}
    for i, sid in enumerate(servo_ids, start=1):
        tk.Label(right, text=sid, font=small, bg="orange").grid(row=i, column=0, sticky="w", padx=(0, 10))
        lbl = tk.Label(right, text="--°", font=small, bg="orange")
        lbl.grid(row=i, column=1, sticky="w")
        servo_labels[sid] = lbl

    pir_labels = {}
    for i, sid in enumerate(["PIR1"], start=3):  # edit IDs for installed PIR nodes
        tk.Label(right, text=sid, font=small, bg="orange").grid(row=i, column=0, sticky="w")
        lbl = tk.Label(right, text="unavailable", font=small, bg="orange")
        lbl.grid(row=i, column=1, sticky="w")
        pir_labels[sid] = lbl

    multi_heard = tk.Label(mid, text="last heard: --", font=small, bg="orange")
    multi_heard.grid(row=2, column=0, columnspan=8, sticky="w")
    lantern_frame = tk.Frame(panel, bg="orange")
    lantern_frame.grid(row=3, column=0, sticky="nw", pady=(4, 0))
    tk.Label(lantern_frame, text="LANTERNS", font=("Helvetica bold", 13), bg="orange").grid(
        row=0, column=0, columnspan=2, sticky="w")
    lantern_labels = {}
    for i, sid in enumerate(["LANTERN1", "LANTERN2", "LANTERN3", "LANTERN4"], start=1):
        tk.Label(lantern_frame, text=sid, font=("Helvetica", 10), bg="orange").grid(
            row=i, column=0, sticky="w", padx=(0, 8))
        lbl = tk.Label(lantern_frame, text="unavailable", font=("Helvetica", 10), bg="orange")
        lbl.grid(row=i, column=1, sticky="w")
        lantern_labels[sid] = lbl
    command_label = tk.Label(panel, text="", font=("Helvetica", 10), bg="orange", wraplength=405, justify="left")
    command_label.grid(row=4, column=0, sticky="w", pady=(4, 0))

    # ===== Live updater (every 100 ms, reads only; no serial waits) =====
    def _update_status():
        for sid, lbl in tof_labels.items():
            value = rsm.get_value(sid, "dist_mm")
            lbl.config(text=f"{value} mm" if value is not None else rsm.device_status(sid)["state"])

        for sid, lbl in btn_labels.items():
            pressed = rsm.get_button_value(sid)
            status = rsm.device_status(sid)
            age = status["age_ms"]
            heard = "--" if age is None else f"{age // 1000}s"
            state = "held" if pressed is True else "sleep" if pressed is False else "?"
            lbl.config(text=f"{state} / {heard}")

        for i, lbl in enumerate(multi_labels):
            value = rsm.get_button_value(multi_id, i + 1)
            lbl.config(text="?" if value is None else str(value))
        age = rsm.device_status(multi_id)["age_ms"]
        multi_heard.config(text="last heard: --" if age is None else f"last heard: {age // 1000}s ago")

        for sid, lbl in servo_labels.items():
            state = rsm.get_servo_state(sid)
            angle = state.get("output_angle")
            if state["state"] in ("stale", "unavailable", "conflict") or angle is None:
                lbl.config(text=state["state"])
            else:
                motion = " moving" if state.get("moving") else ""
                lbl.config(text=f"output {angle} deg{motion}")

        for sid, lbl in pir_labels.items():
            state = rsm.get_pir_state(sid)
            if not state["available"]:
                text = state["state"]
            else:
                text = "HIGH" if state["output"] else "LOW"
                text += " ready" if state["ready"] else " warming"
            lbl.config(text=text)

        for sid, lbl in lantern_labels.items():
            state = rsm.get_lantern_state(sid)
            if not state["available"] or "lantern_state" not in state:
                text = state["state"]
            else:
                names = {"off": "off", "solid_on": "solid", "flickering_on": "flicker",
                         "intense_flickering_on": "intense flicker", "flicker_out": "fading out",
                         "intense_flicker_out": "intense fade out"}
                mode = f"wait {state['next_command_id']}" if state["synced"] else "free"
                text = f"{names[state['lantern_state']]} | {mode}"
            lbl.config(text=text)

        failure = rsm.command_failure()
        health = rsm.healthy()
        if health.get("error") and "conflict" in health["error"].get("message", "").lower():
            message = health["error"]["message"]
        elif failure:
            message = f"{failure['id']}: {failure['status']} ({failure.get('reason', '')})"
        else:
            message = "" if health["connected"] else "Bridge unavailable"
        command_label.config(text=message)
        root.after(100, _update_status)

    root.after(200, _update_status)

    root.mainloop()
