# HauntSim Layout Studio

A standalone Python/Qt desktop application for drawing yearly haunt layouts, configuring event-driven control behavior, watching groups move, and measuring throughput and flow failures. Everything lives in this folder. It does **not** import the live control system, open serial ports, send network commands, or operate hardware.

## Install and launch

Python 3.10+ is required. From PowerShell:

```powershell
cd Simulation
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python run.py
```

Activation is optional; the explicit interpreter paths work even when PowerShell script activation is disabled. If using an existing Python environment:

```powershell
python -m pip install -r requirements.txt
python run.py
```

Open a project on launch with `python run.py examples/three-scenes.hauntsim`.
The only third-party dependency is **PySide6** (Qt widgets, graphics, threads). The simulation, persistence, analytics, and advisor use the Python standard library. Qt's licenses apply to PySide6 redistribution.

## First project

1. Choose **File → New project**, then **Project → Import background**. PNG, JPEG, BMP, WebP and supported TIFF images are accepted. Image bytes are copied into the project. The picture is only artwork: no walls or routes are inferred.
2. Open **Project → Project / run settings**. Name the project, choose feet or meters, and set group size and walking speed in those units. Units should be selected before calibration; changing the unit label does not convert existing values.
3. Choose **Calibrate** and click the two ends of a known dimension. Enter `8` for an eight-foot wall when the project units are feet. Calibration determines pixels per unit. Without calibration, use explicit path travel times.
4. Select **Entrance** and click its position. Create one enabled entrance. Select **Room** and click two opposite corners for each room. Place an **Exit** at the end.
5. Select a room with the **Select** tool. The property dock edits names, capacity, nominal duration, minimum/typical/maximum duration, preferred duration, acceptable advisor bounds, enabled state and notes. Changes apply automatically as you edit. Equal min/typical/max means fixed timing; unequal values use a triangular distribution.
6. Select **Path**. Click from the entrance through route vertices to the first room; double-click or press Enter to finish. Draw one directed path for every connection, such as Entrance → A → B → C → Exit. Arrowheads show direction. Endpoints near node centers are connected automatically; verify **Source** and **Target** in properties. A connection may have arbitrarily many vertices.
7. Path **Travel override** defaults to 5 seconds. Set it to **0** to use calibrated distance / sampled group speed. Each group keeps its sampled speed throughout the visit. Branching is supported: draw multiple outgoing paths and set positive relative branch weights. Routes are sampled once per departure and retained while blocked.
8. Place doors and sensors, then add admission rules as described below.
9. Choose **Project → Validate**, resolve errors, then save a `.hauntsim` file.

**Help → Open example project** provides a three-room layout with a sensor admission rule and an automatic swinging door. The same portable project is in `examples/three-scenes.hauntsim`. Its automatic interior door deliberately causes short flow failures until you configure advance opening.

## Comfortable editing

- Wheel zooms around the cursor. **Pan** drags the view. **View → Fit layout** or `F` fits the drawing.
- Select and drag objects; rubber-band selection selects several. The optional 10-pixel grid snaps object moves and placement.
- Selected paths expose a handle at each vertex; drag handles to reshape the route, or right-click a handle to delete that vertex. A path must retain at least two vertices. The room corner handle resizes the rectangle. The door handle changes its open angle visually. The property form provides precise values.
- Moving connected rooms adjusts the corresponding route endpoints. After major route changes, check sensor placement and door associations.
- `Ctrl+C` / `Ctrl+V` duplicates selected objects, remapping references between copied objects. `Delete` confirms deletion; dangling references are reported by validation. `Ctrl+Z` / `Ctrl+Y` undo/redo model edits, with 60 retained snapshots.
- Right-click exposes copy, paste, delete, finish-path and fit actions. Escape returns to Select. View contains layer switches and dock visibility controls.
- Inspector edits update the layout immediately, preserving focus while you type. Consecutive changes to a field are grouped for undo. Save the project to keep edits on disk; closing, replacing, or creating a project prompts about unsaved changes.
- Editing is locked during visual simulation and background analysis. Use **Reset / Edit** to return to editing.

## Doors

Place a door at its hinge (swing) or slide origin. The editor associates a new or moved door with the nearest path; the door's **Path** property can select another route. Select **swing**, **slide**, or **passage** in properties. Configure opening, closing and hold durations. Swing doors support arbitrary closed and relative open angles; negative open angles reverse direction. Drag the white angle handle for visual direction adjustment. Sliding doors use a displacement vector in layout pixels. Passage objects impose no door delay.

The closed door leaf's intersection with its associated path is the threshold. If the leaf does not cross the line exactly, the nearest route position to the leaf's center is used. A group walks from the source room to that threshold, checks the door, and then completes the remaining path after passage. A stop at a closed interior door is recorded at that physical map position as an interior flow failure. Several doors may reference the same path; they are encountered in their visual order. A door at the very beginning of an entrance path gates admission and preserves pending-release latency behavior. Older projects that stored one door on a path are migrated automatically when opened.

Automatic doors start opening when a group reaches their threshold and close after the configured hold time. This behavior is independent of event-rule conditions. Interior groups must stop if they arrive before the door is open; this is correctly reported as a flow failure. To avoid that stop, use an upstream sensor or room-completed event to open the door early. With Automatic unchecked, rules entirely control opening and closing. Disabling a physical door makes it unavailable; use Passage to model removal of a physical door.

The current door state animates in the layout. Events expose opening, opened, closing and closed transitions. Reversals interpolate from the current position. Door utilization means the fraction of the run spent non-closed, including opening and closing.

## Sensors and release rules

Place a sensor near a route; the editor assigns its nearest path and fraction automatically. Its logical location is **Associated path + Position along path (0–1)**, not proximity to the picture. Edit those properties to change when it fires. Cooldown suppresses repeated triggers for the configured simulated seconds. Routes are directed, so sensor direction is inherited from the path.

In the **WHEN / IF / THEN rules** dock, choose Add:

- Event: `sensor_crossed`
- Source: your sensor
- Condition: `always`
- Action: `admit`
- Target: the entrance (or empty, since the model has one entrance)
- Delay: `0`

Enable **Release first group at start** in project settings. This yields: group 1 enters at start; its sensor crossing signals the next admission; each subsequent crossing continues the chain. There is **no default periodic release timer**.

Other events include simulation start, haunt entry/exit, room entry/timer completion/exit, path entry/exit, location reached, door transitions and custom signals. Conditions include room available/empty/occupied, path clear, door open/closed, and object or rule enabled/disabled. Actions admit, open/close doors, enable/disable objects or rules, and emit custom signals. Source may be empty to match any source. Custom signal identifiers can be typed into the editable Source/Target selectors. Rules contain no executable user code.

Enable **Remember the event until its condition becomes true** when a trigger must be latched. For example: WHEN `Sensor 2` is crossed, IF `Room B` is available, THEN open `Door 2`. If Room B is occupied at the crossing, the engine stores one pending activation and reevaluates it after later simulation state changes. The action fires once when Room B gains capacity. Repeated sensor events while it is pending are coalesced and recorded in the event log. With remembering disabled, the condition is checked only at the instant of the source event. This is event-driven reevaluation rather than timer polling.

If the entrance is busy, one release remains pending. Additional signals merge into that pending release and are explicitly counted as coalesced/blocked signals. The original signal time and actual admission time determine latency. Admission also respects an optional finite exterior group count; `0` means an unlimited exterior supply. Outside waiting is never labeled an interior queue.

Disable initial release for a manual start and use **Release** to send the first admission request. The validation warning explains this mode. Cyclic custom signals are rejected and runtime event limits guard other runaway configurations.

## Running and watching

The toolbar provides Run/Resume, Pause, Stop, Reset/Edit, single-event Step, Manual Release, and Fast analysis. Speeds are 1×, 2×, 5×, 10×, 25×, and 50×. The duration selector includes 10/30/60 minutes and two hours. Project settings provide custom seconds, completion targets in groups or guests, and manual stop.

Groups move along the exact polyline paths. Green means walking, blue means a scene, orange means room overstay, and red means an interior stop. Hover over a marker for its group ID, guest count, location, speed, elapsed visit time, and blocked time. The status bar reports simulated time, occupancy, completions, recent five-minute groups, and failure count.

The optional log dock filters by event text, object name or `group:12`, with buffered display of the last 1,000 matching rows. Press `Ctrl+F` to show the dock and focus its search field. The **Auto-scroll** toggle follows new matching lines when enabled and preserves your reading position when disabled. The engine retains at most 100,000 log records; analytics are collected independently. Fast analysis does not update graphical frames or the log display for each event.

**Stop** collects results at the current time. Reset unlocks editing and keeps the last result available. If the event calendar empties, visual playback pauses so you can manually release or inspect a deadlock. Headless time-based runs integrate the remaining occupancy/blockage through the requested horizon. Fast manual-stop projects use the configured duration. Repeated runs, comparisons and the advisor always use the configured duration, for comparable measurements. Long jobs run in a Qt worker with a Cancel button.

## Flow model and analytics

The engine is a deterministic discrete-event calendar ordered by `(time, insertion sequence)`. Rendering interpolates its state; changing animation speed or frame frequency does not change the simulated outcome.

- Rooms have finite capacity and begin their scene timer on actual entry.
- Each directed path is a **single-group movement segment**. A group occupies it until its destination accepts it. A second group waits in its upstream room if that segment is occupied. This prevents overtaking or overlapping groups on the same segment.
- A group whose scene finishes but whose outgoing segment is unavailable stays associated with its room: **room overstay**. Expected release, actual release and downstream cause are recorded.
- Once a group has left a room, reaching a closed door threshold or unavailable destination room is an **interior flow failure**. The marker remains at the actual blocking point. There are no generic normal hallway queue objects.
- Piecewise-linear closest-approach checks flag **spacing conflicts** between groups on distinct crossing/overlapping paths, using path spacing in layout pixels. These are warnings about the authored route geometry; the engine never invents an avoidance path.

Analytics includes groups/guests per hour, 5/10/15/30-minute buckets, visit-time mean/median/range, current/max occupancy, room utilization and intended/actual duration, room overstays, interior failures and causes, longest/total blockage, walking/scene/blocked time, path times, sensor counts, door cycles/utilization, release constraints and latency. Ongoing occupancy and blockages at the run cutoff are included; ongoing room visits are censored and labeled in full data. Hourly throughput is completed count divided by the entire run duration, including startup, not an assumed steady-state rate. Room utilization divides occupied group-seconds by capacity × run duration.

Charts cover occupancy, cumulative completions, throughput, room utilization, overstays, blocked time, failures and release latency. Diagnose actual observed causes in the Diagnosis tab. Low utilization may indicate upstream starvation, but the report does not claim a unique causal explanation from utilization alone.

**Analytics → Map overlay** highlights high-utilization/problem rooms, blocking doors and affected paths in red. Select an object to see its relevant last-run metrics. **File → Export results CSV** exports metrics and detailed records; full JSON exports configuration, seed, timestamp, settings, series and per-location records for reproducibility.

## Scenarios, repeated runs and timing advisor

Use **Project → Duplicate scenario**, then select it in the toolbar. Its property edits override simulation parameters; the base geometry/background remain shared. Settings and rules can be varied per scenario. Geometry is editable only in Base. Scenarios can be renamed and deleted. **Analytics → Compare scenarios** runs each scenario with a common seed and displays throughput, traversal time, failures, overstays, peak groups and latency.

Repeated simulations accept 100, 500, 1000 or any custom count. Runs use consecutive seeds starting at the configured seed. The summary includes mean/median throughput, 5th/95th percentiles, guest throughput, fraction of runs with interior failures, average failures, recurring blocking entities and room utilization distributions. Percentiles are descriptive empirical ranges, not confidence intervals.

The timing advisor uses two bounded coordinate-search passes and three common seeds per candidate. It ranks interior failure count and blocked time first, then throughput discounted for deviation from preferred scene durations and overstay. It tests acceptable min/preferred/max and nearby timings while preserving triangular ranges within bounds. Recommendations show current/suggested timings and estimated effects. **Save recommendation as a new scenario** preserves the original configuration. This is a local search, not a global optimum or a guarantee for live operation. Re-run Monte Carlo analysis before adopting a recommendation.

## Storage and architecture

`.hauntsim` is a ZIP containing `project.json` and optional `assets/background` (original image bytes, detected by content). Schema version 1 is explicit. Unsupported versions are rejected rather than guessed; future migrations should be explicit. Saves write a temporary sibling, flush/fsync, then atomically replace the destination. Project files have a 100 MB uncompressed load limit; imported images are limited to 50 MB.

Only the latest 20 compact run summaries are retained in the project, preventing unbounded detailed-history growth. Full current-run details are exported separately. Geometry and shared assets are not duplicated for scenarios. Normal preferences/recent projects use QSettings.

- `hauntsim/model.py`: configuration and geometry
- `persistence.py`, `validation.py`: portable storage and preflight checks
- `engine.py`: event calendar, rules, admission, movement, occupancy and doors
- `analytics.py`, `analysis_jobs.py`: results, repeated runs and timing advisor
- `editor.py`, `forms.py`: layout graphics and typed property/rule forms
- `app.py`, `reports.py`, `workers.py`: desktop shell, charts and background jobs
- `tests/`: core regression and offscreen Qt workflow tests

## Verification

From this folder:

```powershell
python -m unittest discover -s tests -v
```

Tests cover persistence/version handling and legacy door migration, interrupted saves, triangular timing and group sizes, geometry, deterministic ordering, sensor release, middle-of-path and multiple-door thresholds, door transitions, capacities, pending admission, ongoing blockages, overstays, throughput, frame-rate independence, scenarios, advisor bounds, repeated runs, cancellation, validation, and real Qt editing/import/calibration/simulation/save/reopen workflows.

## Modeling limits

Rooms are rectangles; paths are editable polylines. Guests are not individually simulated, and there is no collision inference from background images. Path segments are exclusive to one group, so choose segment boundaries deliberately; this is a conservative flow model, not pedestrian fluid dynamics. Sensor direction follows directed paths. Door thresholds use the closed leaf's line intersection, but crossing has no separately simulated group body length. Branch selection is weighted stochastic routing, not conditional per-group itineraries. The advisor optimizes room timings, not layout geometry, door timing or rule topology. Large visual scenes and extremely long/high-volume runs remain bounded by memory and a two-million-event analytical safety limit. No packaged Windows installer is supplied; launch from Python.
