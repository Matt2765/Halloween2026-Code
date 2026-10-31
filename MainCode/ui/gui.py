# ui/gui.py
import tkinter as tk
import threading
from MainCode.rooms import CabinRoom, Bathroom, ShowerHallway, DynamicHallway, Basement, PalletHallway, ForestHallway
from context import house
from control.shutdown import shutdown
from control.doors import DOOR_SOLENOID_PINS, setDoorState
from control.houseLights import toggleHouseLights
from utils.tools import log_event

# NEW: read-only sensor values
from control import remote_sensor_monitor as rsm  # minimal addition
from control.animatronic_service import start_pedro, stop_pedro, pedro_status


def demoEvent(room):
    house.Demo = True
    house.HouseActive = True
    toggleHouseLights(False)
    log_event(f"[GUI] Starting demo of {room}")

    if room == CabinRoom.__name__.split('.')[-1]:
        threading.Thread(target=CabinRoom.run, args=(), name=f"{room} demo").start()
    elif room == Bathroom.__name__.split('.')[-1]:
        threading.Thread(target=Bathroom.run, args=(), name=f"{room} demo").start()
    elif room == ShowerHallway.__name__.split('.')[-1]:
        threading.Thread(target=ShowerHallway.run, args=(), name=f"{room} demo").start()
    elif room == DynamicHallway.__name__.split('.')[-1]:
        threading.Thread(target=DynamicHallway.run, args=(), name=f"{room} demo").start()
    elif room == Basement.__name__.split('.')[-1]:
        threading.Thread(target=Basement.run, args=(), name=f"{room} demo").start()
    elif room == PalletHallway.__name__.split('.')[-1]:
        threading.Thread(target=PalletHallway.run, args=(), name=f"{room} demo").start()
    elif room == ForestHallway.__name__.split('.')[-1]:
        threading.Thread(target=ForestHallway.run, args=(), name=f"{room} demo").start()


def change_system_state(new_state):
    house.systemState = new_state


def MainGUI():
    from control.system import StartHouse
    log_event(f"[GUI] Booting main GUI...")

    root = tk.Tk()
    root.configure(background="orange")
    root.title("Halloween [year] Control Panel")
    root.geometry("465x900")

    # Let sections follow their requested height instead of leaving fixed gaps.
    content = tk.Frame(root, bg="orange")
    content.pack(fill="x", padx=16, pady=10)
    control_font = ("Helvetica", -13)
    heading_font = ("Helvetica bold", -17)

    def section(title):
        tk.Label(content, text=title, font=heading_font, bg="orange").pack(
            anchor="w", pady=(4, 2))
        frame = tk.Frame(content, bg="orange")
        frame.pack(fill="x", pady=(0, 4))
        return frame

    def control(frame, text, command, row, column, bg=None, state="normal"):
        frame.grid_columnconfigure(column, weight=1, uniform="controls")
        options = {"bg": bg} if bg else {}
        tk.Button(frame, text=text, font=control_font, height=1,
                  command=command, state=state, **options).grid(
            row=row, column=column, sticky="ew", padx=2, pady=2, ipady=3)

    mains = section("MAINS")
    control(mains, "EMERGENCY SHUTOFF",
            lambda: change_system_state("EmergencyShutoff"), 0, 0, "red")
    control(mains, "START HAUNTED HOUSE",
            lambda: threading.Thread(target=StartHouse, daemon=True, name="HOUSE").start(),
            0, 1, "turquoise1")
    control(mains, "SOFT SHUTDOWN",
            lambda: change_system_state("SoftShutdown"), 1, 0, "yellow")
    control(mains, "Toggle House Lights", toggleHouseLights, 1, 1, "chartreuse2")

    doors = section("DOOR CONTROLS")
    for i, door in enumerate(sorted(DOOR_SOLENOID_PINS)):
        row, column = i // 3, (i % 3) * 2
        state = "normal" if door in DOOR_SOLENOID_PINS else "disabled"
        control(doors, f"Open {door}",
                lambda door=door: setDoorState(door, "OPEN"), row, column, state=state)
        control(doors, f"Close {door}",
                lambda door=door: setDoorState(door, "CLOSED"), row, column + 1, state=state)
    unmapped = [str(door) for door in range(1, 7) if door not in DOOR_SOLENOID_PINS]
    if unmapped:
        tk.Label(doors, text=f"Doors {', '.join(unmapped)}: hardware mapping needed",
                 font=control_font, bg="orange").grid(
            row=2, column=0, columnspan=6, sticky="w", padx=2)

    demos = section("DEMO CONTROLS")
    for i, room in enumerate((CabinRoom, Bathroom, ShowerHallway, DynamicHallway,
                              Basement, PalletHallway, ForestHallway)):
        name = room.__name__.split('.')[-1]
        control(demos, f"Demo {name}", lambda name=name: demoEvent(name), i // 3, i % 3)
    control(demos, "Start Pedro",
            lambda: threading.Thread(target=start_pedro, daemon=True, name="Pedro start").start(),
            2, 1)
    control(demos, "Stop Pedro",
            lambda: threading.Thread(target=stop_pedro, daemon=True, name="Pedro stop").start(),
            2, 2)

    panel = section("SENSORS & BUTTONS")

    # Pixel-sized status fonts keep this panel within the fixed window at high DPI.
    small = ("Helvetica", -13)
    status_heading = ("Helvetica bold", -17)

    # ===== Row group 1: TOF + Buttons + PIR =====
    row1 = tk.Frame(panel, bg="orange")
    row1.grid(row=0, column=0, sticky="nw")

    # TOF table
    tof_frame = tk.Frame(row1, bg="orange")
    tof_frame.grid(row=0, column=0, sticky="nw", padx=(0, 10))
    tk.Label(tof_frame, text="TOF", font=small, bg="orange").grid(row=0, column=0, sticky="w", padx=(0, 10))
    tk.Label(tof_frame, text="Dist", font=small, bg="orange").grid(row=0, column=1, sticky="w")

    tof_ids = [f"TOF{i}" for i in range(1, 7)]
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

    btn_ids = [f"BTN{i}" for i in range(1, 7)]
    btn_labels = {}
    for i, sid in enumerate(btn_ids, start=1):
        tk.Label(btn_frame, text=sid, font=small, bg="orange").grid(row=i, column=0, sticky="w", padx=(0, 6))
        lbl = tk.Label(btn_frame, text="?", font=small, bg="orange")
        lbl.grid(row=i, column=1, sticky="w")
        btn_labels[sid] = lbl

    # PIR table: seven nodes in their own sensors column.
    pir_frame = tk.Frame(row1, bg="orange")
    pir_frame.grid(row=0, column=2, sticky="nw", padx=(10, 0))
    tk.Label(pir_frame, text="PIR", font=small, bg="orange").grid(
        row=0, column=0, columnspan=2, sticky="w")
    pir_ids = [f"PIR{i}" for i in range(1, 8)]
    pir_labels = {}
    for i, sid in enumerate(pir_ids, start=1):
        tk.Label(pir_frame, text=sid, font=small, bg="orange").grid(
            row=i, column=0, sticky="w", padx=(0, 6))
        lbl = tk.Label(pir_frame, text="unavailable", font=small, bg="orange")
        lbl.grid(row=i, column=1, sticky="w")
        pir_labels[sid] = lbl

    # ===== Row group 2: SERVOS =====
    right = tk.Frame(panel, bg="orange")
    right.grid(row=1, column=0, sticky="nw", pady=(6, 0))

    tk.Label(right, text="SERVOS", font=status_heading, bg="orange").grid(row=0, column=0, columnspan=4, sticky="w")

    servo_ids = ["DROPDOWN1", "SERVO1", "SERVO2"]  # edit as needed
    servo_labels = {}
    for i, sid in enumerate(servo_ids):
        row, column = (1, 0) if sid == "DROPDOWN1" else (3, (i-1)*2)
        tk.Label(right, text=sid, font=small, bg="orange").grid(row=row, column=column, sticky="w", padx=(0, 6))
        lbl = tk.Label(right, text="--°", font=small, bg="orange")
        lbl.grid(row=row, column=column+1, columnspan=3 if sid == "DROPDOWN1" else 1,
                 sticky="w", padx=(0, 12))
        servo_labels[sid] = lbl

    tk.Label(right, text="Dropdown sensor", font=small, bg="orange").grid(
        row=2, column=0, sticky="w", padx=(0, 6))
    dropdown_button_label = tk.Label(right, text="unknown", font=small, bg="orange")
    dropdown_button_label.grid(row=2, column=1, columnspan=3, sticky="w", padx=(0, 12))

    lantern_frame = tk.Frame(panel, bg="orange")
    lantern_frame.grid(row=2, column=0, sticky="nw", pady=(4, 0))
    tk.Label(lantern_frame, text="LANTERNS", font=status_heading, bg="orange").grid(
        row=0, column=0, columnspan=2, sticky="w")
    lantern_labels = {}
    for i, sid in enumerate(["LANTERN1", "LANTERN2", "LANTERN3", "LANTERN4"], start=1):
        tk.Label(lantern_frame, text=sid, font=small, bg="orange").grid(
            row=i, column=0, sticky="w", padx=(0, 8))
        lbl = tk.Label(lantern_frame, text="unavailable", font=small, bg="orange")
        lbl.grid(row=i, column=1, sticky="w")
        lantern_labels[sid] = lbl
    command_label = tk.Label(panel, text="", font=small, bg="orange", wraplength=405, justify="left")
    command_label.grid(row=3, column=0, sticky="w", pady=(4, 0))
    pedro_label = tk.Label(panel, text="Pedro stopped", font=small, bg="orange", wraplength=405, justify="left")
    pedro_label.grid(row=4, column=0, sticky="w", pady=(4, 0))

    # ===== Live updater (every 100 ms, reads only; no serial waits) =====
    def _update_status():
        pressed = rsm.get_button_value("DROPDOWN1")
        dropdown_status = rsm.device_status("DROPDOWN1")
        if not dropdown_status.get("available"):
            pressed = None
        dropdown_age = dropdown_status.get("age_ms")
        heard = "--" if dropdown_age is None else f"{dropdown_age / 1000:.1f}s"
        button_text = ("True (pressed)" if pressed is True else
                       "False (released)" if pressed is False else
                       f"unknown ({dropdown_status['state']})")
        dropdown_button_label.config(text=f"{button_text} / {heard}")
        pedro = pedro_status()
        pedro_text = "running" if pedro["running"] and pedro["connected"] else "waiting for link" if pedro["running"] else "idle animations" if pedro.get("mode") == "idle" else "stopped"
        pedro_label.config(text=f"Pedro {pedro_text} | {pedro['channel']}" +
                           (f" | {pedro['error']}" if pedro["error"] else ""))
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

        for sid, lbl in servo_labels.items():
            state = rsm.get_servo_state(sid)
            angle = state.get("output_angle")
            age = state.get("age_ms")
            heard = "--" if age is None else f"{age / 1000:.1f}s"
            if state["state"] in ("stale", "unavailable", "conflict") or angle is None:
                text = state["state"]
            else:
                motion = " move" if state.get("moving") else ""
                text = f"PWM {angle}°{motion}"
            lbl.config(text=f"{text} / {heard}" if sid == "DROPDOWN1" else text)

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
                         "intense_flicker_out": "intense fade out", "strobe": "strobe"}
                mode = f"wait {state['next_command_id']}" if state["synced"] else "free"
                text = f"{names[state['lantern_state']]} | {mode}"
            lbl.config(text=text)

        failure = rsm.command_failure()
        health = rsm.healthy()
        if health["disabled"]:
            message = "RSM DISABLED"
        elif health.get("error") and "conflict" in health["error"].get("message", "").lower():
            message = health["error"]["message"]
        elif not health["connected"]:
            message = "Bridge unavailable"
        elif failure:
            detail = failure.get("detail") or failure.get("reason", "")
            message = (f"Last failure ({failure['age_ms'] // 1000}s ago): "
                       f"{failure['id']} {failure.get('op', '')}: {failure['status']} ({detail})")
        else:
            message = "" if health["connected"] else "Bridge unavailable"
        command_label.config(text=message, fg="red" if health["disabled"] else "black")
        root.after(100, _update_status)

    root.after(200, _update_status)

    root.mainloop()
