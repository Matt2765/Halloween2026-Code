Build a complete reusable haunted-house simulation, visualization, layout-editing, and throughput-analysis desktop application inside this repository.

This should be a finished usable application, not a prototype, partial scaffold, architecture proposal, or collection of TODOs.

Before modifying anything:

1. Inspect the current repository thoroughly.
2. Locate the existing `simulation` directory in the current working tree.
3. Understand the existing Python project structure and dependency conventions.
4. Keep this simulator isolated from the live haunted-house control system. It may reuse generic utilities if truly appropriate, but it must not create dependencies where the simulator can accidentally operate real hardware.
5. If the current working tree does not actually contain a `simulation` directory, create one at the repository root rather than blocking on the discrepancy.
6. Do not ask me architectural questions unless something is literally impossible to infer. Make sensible decisions and implement the complete system in one pass.

The simulator must be completely configuration-driven. I should never need to edit Python code to create a haunt for a new year.

The goal is that every year I can launch this program, choose File -> New Project, import an overhead image of that year's haunted-house layout, draw/configure the rooms, paths, doors, sensors, timings, and trigger behavior, then simulate the haunt and analyze throughput and bottlenecks.

## Technology

Use Python.

Prefer PySide6 / Qt for the desktop application because this needs a proper desktop GUI with menus, dialogs, dock/panel-style property editing, a graphical layout editor, zoom/pan, draggable objects, animation, charts, and multiple views.

Keep the simulation engine cleanly separated from the GUI/rendering layer.

The core simulation must be a discrete-event simulation. Do NOT base simulation accuracy on a graphical frame loop.

The GUI should animate/interpolate the underlying simulation state when visually watching a run, while analytical runs should be able to execute as fast as the CPU can reasonably process them without rendering every frame.

Avoid unnecessary heavy dependencies. Add/document whatever dependencies are genuinely required.

Provide a straightforward launch method from the `simulation` folder and document it in a README.

## Core philosophy

There are several important rules that must shape the design.

### 1. Do not hard-code the current haunt

The application itself must know nothing about names such as Cave, Mirror, Swamp, Mask, Graveyard, etc.

Those belong only in project files made with the editor.

The same application must work for completely different layouts in later years.

### 2. The imported floor-plan image is only a backdrop

The simulation must NOT attempt to infer walls, routes, or rooms from the picture.

I will explicitly configure the simulation graph over the picture.

### 3. Groups follow user-created paths

Groups must never invent their own navigation.

I will draw paths over the layout indicating where groups actually walk.

Groups should smoothly animate along those paths.

### 4. Rooms are the intended holding/buffering locations

Do NOT design normal internal "queue points" or hallway holding areas.

A group waiting outside before entering the haunt is completely normal.

A group being forced to stop in a hallway, in front of an interior door, between scenes, or at another unintended location is BAD and should be detected and prominently reported.

If a room's intended scene has completed but the group cannot leave normally because downstream flow is backed up, record that separately as a room overstay/downstream blockage.

Those are important analytics.

### 5. Entry is event-driven, not timer-driven

Do NOT implement the primary admission model as "release a group every X seconds."

The actual haunted house determines when the next group is admitted.

For example:

* Group A crosses a particular sensor.
* That sensor tells the entrance/front door to open.
* The front door admits Group B.
* Later Group B trips the same sensor and admits Group C.

Or:

* A particular interior door begins opening.
* That event signals the front entrance to release the next group.

Or:

* A group reaches/leaves a configured location.
* That signal admits the next group.

The simulator therefore needs a configurable signal/event/action system that can reproduce this behavior without requiring custom Python code.

An interval-based timing tool can exist for testing if useful, but it must NOT be the fundamental admission mechanism or default model.

## Application shell

Create a polished normal desktop application with menus approximately like:

File
Edit
View
Project
Simulation
Analytics
Help

Support at minimum:

File -> New Project
File -> Open Project
File -> Save
File -> Save As
File -> Recent Projects
File -> Close Project
File -> Exit

Useful export functionality should also be available for analytics.

Use normal keyboard shortcuts where appropriate:

Ctrl+N
Ctrl+O
Ctrl+S
Ctrl+Shift+S
Ctrl+Z
Ctrl+Y
Delete
Ctrl+C
Ctrl+V

Persist normal application preferences/recent projects using an appropriate Qt settings mechanism.

## Project file format

Create a portable project format, preferably something like:

`MyHaunt2026.hauntsim`

I would prefer this to behave as a single portable project file from the user's perspective.

Internally it can be a ZIP-style container holding something like:

project.json
assets/background.png
other future assets

Use Python's standard ZIP support if appropriate.

The project data must include a schema/project format version so future program versions can migrate old projects safely.

When a background image is imported, COPY it into the project rather than storing a fragile absolute path to the original image.

Use atomic/defensive saving so an interrupted save is unlikely to destroy a project.

## Main interface

The primary layout should have:

* central graphical haunt editor/viewer
* tool palette
* object/property inspector
* simulation controls/status
* easy switching between editing, simulation, and analytics

The visual style should be clean and functional rather than excessively fancy.

This application should feel hand-built and understandable rather than like an overengineered commercial CAD package.

## Layout editor

The central editor should display the imported overhead image.

Support:

* zoom using mouse wheel
* pan
* selection
* multi-select where useful
* drag/move objects
* optional snapping
* delete
* copy/paste
* undo/redo
* useful context menus
* edit mode vs simulation mode so objects cannot accidentally be moved during a run
* fit image/layout to view
* layer visibility controls where useful

Provide tools for at least:

Select
Room
Path
Door
Sensor
Entrance
Exit

Potentially support labels/annotations if easy to integrate cleanly.

## Background image and real-world scale

Allow importing common image formats.

Provide a scale calibration tool:

1. User draws/clicks two points over a known dimension.
2. User enters its real-world length, e.g. 8 feet.
3. The project then knows pixels-per-foot or pixels-per-meter.

Support units such as feet and meters.

This allows path distance and walking duration to be calculated from the layout.

If no scale is configured, still allow path travel times to be entered manually.

## Rooms

Allow rooms to be drawn over the floor plan.

Rectangles should be easy, but polygon rooms would be useful if they can be implemented reliably.

Each room should have editable properties such as:

* unique ID
* display name
* preferred/nominal scene duration
* minimum acceptable scene duration
* maximum acceptable scene duration
* timing mode
* capacity in groups
* optional notes
* associated entry/exit connections
* enabled/disabled

Room timing should support at least:

Fixed duration

and

Variable duration

For variable timing, make the UI simple:

Minimum
Typical
Maximum

A triangular distribution using Typical as the mode would be a sensible internal implementation.

If min = typical = max, it is effectively fixed.

Room timing begins when the group actually enters/occupies the room according to the simulation model.

Track both:

* intended room/scene duration
* actual time the group remained associated with the room

If actual occupancy significantly exceeds intended duration because downstream progression is blocked, log a room-overstay event and record its cause.

## Walking paths

Allow the user to draw polyline routes over the backdrop by clicking points.

The editor should make drawing/editing paths intuitive.

Paths form the actual movement graph of the simulation.

Groups must move along them rather than straight-line teleporting between rooms.

Calculate travel time using:

distance / group walking speed

when project scale is known.

Allow an explicit travel-time override as well.

The underlying data model should support branching/multiple paths even if most projects use one linear haunt route.

Make route connectivity visually obvious.

Validate broken/disconnected routes.

## Group representation

Groups should be represented visually as small circles/markers moving through the layout.

Display a useful group identifier.

Hovering/selecting a group during simulation should reveal details such as:

* group number
* guest count
* time inside haunt
* current room/path/door
* current state
* current speed
* any current delay/blockage
* accumulated wait/blocked time

Use visually distinguishable states for things such as:

walking
inside room
entering/exiting
blocked
completed

Do not require each individual guest to be physically simulated. The primary moving unit is a group.

## Group sizes

Support configurable group sizes.

At minimum:

Fixed size

or

Minimum / Typical / Maximum

Again, a simple triangular distribution is acceptable for variable group size.

Analytics must report BOTH:

groups

and

individual guests

because groups/hour and guests/hour are both important.

## Walking speed

Support configurable group walking speed.

Allow either:

fixed speed

or

minimum / typical / maximum

when desired.

Use calibrated path length to determine actual movement time.

## Doors

Allow doors to be placed visually on the map.

Support at least:

Swinging door
Sliding door
Open passage / no physical door

### Swinging doors

Properties should include:

* hinge point/orientation
* closed angle
* open angle
* swing direction
* opening duration
* closing duration
* hold-open duration if used
* enabled/disabled
* optional automatic behavior
* optional associated signal rules

The editor should make swing direction easy to configure visually rather than requiring obscure numeric setup.

During simulation, the door should visibly rotate about its hinge.

Allow arbitrary opening angles rather than forcing exactly 90 degrees.

### Sliding doors

Support:

* slide direction/vector
* slide distance
* opening duration
* closing duration
* hold-open duration

Animate them accordingly.

### Door state

Track useful states such as:

Closed
Opening
Open
Closing

Door events must be exposed to the trigger/rule system.

Examples:

door started opening
door fully opened
door started closing
door fully closed

## Virtual sensors / trigger points

Provide configurable virtual sensors that can be placed on or near the route.

They do not need to model actual electronics.

They represent logical real-world triggers.

Example:

`Mirror Exit Sensor`

When a group crosses its configured location, generate an event.

Useful properties:

* name
* sensor ID
* enabled
* associated path/location
* trigger direction if relevant
* cooldown/debounce if useful

These events must feed the event/action rule system.

## Event / signal / action system

This is extremely important.

Create a user-friendly rules editor so haunt control behavior can be configured without programming.

Avoid exposing raw code.

A rule should conceptually look like:

WHEN [event]
IF [optional conditions]
THEN [action]

Support source events such as:

Simulation started
Group entered haunt
Group entered room
Group room timer completed
Group exited room
Group crossed sensor
Group reached path node/location
Group entered path
Group exited path
Door started opening
Door fully opened
Door started closing
Door fully closed
Group exited haunt

Support useful actions such as:

Admit/release next exterior group
Open door
Close door
Enable door
Disable door
Enable sensor/rule
Disable sensor/rule
Generate/log custom signal

The rule system should be general enough that future events/actions can be added cleanly.

### Entrance release example

I need to be able to configure logic equivalent to:

WHEN:
Group crosses `Cave Exit Sensor`

THEN:
Admit next waiting group through `Front Entrance`

Or:

WHEN:
`Door 3` begins opening

THEN:
Admit next group

This is the primary way groups should enter the haunt.

### Exterior queue

Assume there can be an effectively unlimited line of groups waiting OUTSIDE unless the user configures a finite number.

Outside waiting is not an interior bottleneck.

The first group should have a configurable initial-release behavior such as:

* release at simulation start
* manual start release
* configured event

Once released, subsequent admission should follow the configured event system.

### Entrance busy behavior

If an entry-release signal occurs while the entrance/front door is physically unable to accept the next group, handle it deterministically.

A sensible default is to retain one pending release and admit the group as soon as the entrance becomes available.

Track:

* signal time
* actual admission time
* release latency

Do not silently lose events.

If repeated release signals exceed what the entrance can physically honor, report that in analytics as an entrance/door constraint rather than an interior hallway queue.

## Room capacity and occupancy

Each room must have a configurable capacity in groups.

Usually this will be 1, but some spaces may support more.

Track occupancy correctly.

Do not allow groups to phase through one another or magically enter beyond configured capacity.

If a group reaches an interior room/door that cannot accept it yet, the group may be forced to stop.

That is an important failure condition.

## Internal blockage detection

This is a critical feature.

There are intentionally NO generic "holding points" throughout the haunt.

Rooms are supposed to provide the spacing.

Detect and record situations where flow breaks down.

At minimum distinguish:

### Room overstay

The group's intended room duration has completed but its progression is delayed by downstream conditions.

Record:

* room
* group
* expected release time
* actual release time
* extra duration
* downstream cause

### Interior flow failure

A group has left its normal room/holding area and is forced to stop at an interior door, hallway, path segment, or room entrance because the path ahead is not ready.

This should be visually obvious during the simulation.

Record:

* group
* location
* start/end time
* duration
* blocking entity
* probable upstream/downstream cause

### Spacing conflict

If groups become unrealistically close on a path or overlap physically according to the configured visualization/spacing model, flag it.

Do not treat these as normal harmless queues.

They are indicators that the timing/control scheme needs adjustment.

## Simulation controls

Provide controls for:

Run
Pause
Resume
Stop
Reset
Step/event-step if practical

Simulation speed choices should include several visual speeds such as:

1x
2x
5x
10x
25x
50x

and a maximum/fast-analysis mode that does not attempt to render every simulated instant.

Display current simulation information such as:

simulated time
groups currently inside
guests currently inside
groups completed
guests completed
recent throughput
current warnings/failures

## Simulation duration

Allow runs based on:

* simulated minutes/hours
* number of completed groups
* number of completed guests
* until manually stopped

Useful presets:

10 minutes
30 minutes
60 minutes
2 hours

plus custom.

Analytical simulations must run much faster than real time.

## Deterministic random seeds

Any randomness must use controllable seeds.

Allow:

Random seed

or

Reproducible specified seed

This is important for comparing scenarios.

Store the seed in simulation results.

## Analytics

Create a substantial analytics view.

At minimum calculate:

* simulated duration
* total groups admitted
* total groups completed
* total guests admitted
* total guests completed
* groups per hour
* guests per hour
* groups per 5 minutes
* groups per 10 minutes
* groups per 15 minutes
* groups per 30 minutes
* guests over equivalent intervals
* average group time through haunt
* median group time through haunt
* minimum/maximum haunt traversal time
* current/max simultaneous groups inside
* current/max simultaneous guests inside
* room occupancy/utilization
* average intended room duration
* average actual room occupancy
* room overstay count
* room overstay duration
* door cycle counts
* door utilization
* sensor trigger counts
* entrance release-signal count
* entrance release latency
* blocked release signals
* interior flow failure count
* total interior blocked time
* longest interior blockage
* spacing-conflict count
* path travel times
* time spent walking
* time spent in scenes
* time spent blocked

Provide useful charts for things like:

throughput over time
groups currently inside over time
guests currently inside over time
room utilization
room overstays
blocked time by location
flow failures over time
entrance release latency
completed guests/groups over time

Allow analytics/results export to CSV where sensible.

## Visual bottleneck overlay

Provide an analytics overlay on the actual haunt map.

After a run, allow the map to visually highlight areas with problems such as:

* frequent room overstays
* interior blockages
* heavily utilized rooms
* frequently constrained doors
* spacing conflicts

Selecting/highlighting an item should show its relevant metrics.

This should make it possible to visually identify where the haunt backs up.

## Bottleneck analysis

Do more than simply label the room with the longest scene time.

Diagnose actual flow behavior.

Analyze things such as:

* occupancy/utilization
* repeated room overstay
* downstream blocking
* upstream starvation
* interior blockage
* entrance limitations
* door cycle limitations
* trigger/release latency
* growing congestion over time

Produce understandable explanations.

Examples:

`Mirror is occupied 96% of the run and caused 18 downstream delays.`

`Groups leaving Cave were blocked at Mirror's entrance 11 times for a total of 84 seconds.`

`Graveyard was only occupied 41% of the run because it was frequently starved by upstream timing.`

Do not fabricate certainty if multiple causes contribute.

## Timing advisor / optimization

Build a timing advisor.

Each room has:

Preferred duration
Minimum acceptable duration
Maximum acceptable duration

Do NOT simply call "minimum room time everywhere" optimal.

That would technically maximize flow while ruining the show.

Instead, optimize for something closer to:

1. prevent interior flow failures
2. achieve stable flow
3. maximize sustainable guests/groups per hour
4. minimize unnecessary waiting/overstay
5. keep room timings as close as reasonably possible to their preferred values

The advisor can use repeated simulations, search/sweeps, hill climbing, or another sensible numerical method.

It should test candidate timing configurations within the user-provided min/max bounds.

Return recommendations such as:

Current:
Cave 25 sec
Mirror 30 sec
Swamp 20 sec
Mask 24 sec

Suggested:
Cave 24 sec
Mirror 23 sec
Swamp 20 sec
Mask 24 sec

Estimated effects:

* fewer internal blockages
* throughput change
* change in average traversal time
* rooms causing the change

Include explanations, not just numbers.

The optimization should remain cancellable/responsive from the GUI.

## Monte Carlo / repeated simulation analysis

Support repeated runs.

Examples:

100 runs
500 runs
1000 runs
custom

Each run should vary configured random timings/group sizes/walking speeds.

Summarize:

mean throughput
median throughput
useful percentiles/ranges
mean guests/hour
mean groups/hour
probability/frequency of interior flow failures
average blockages
worst recurring bottleneck
room utilization distributions

Keep the UI understandable; the user should not need statistics expertise.

## Scenario system

Allow multiple configurations/scenarios derived from the same layout.

Example scenarios:

Base
Changed Mirror Timing
Faster Cave
Different Door Timing
Alternate Release Trigger

A scenario should be able to override relevant simulation parameters without requiring duplication of the entire project artwork/layout.

Provide a comparison view with columns such as:

Groups/hour
Guests/hour
Average traversal time
Interior failures
Room overstays
Max simultaneous groups
Entrance release latency

Allow scenarios to be duplicated and renamed.

## Validation

Before a simulation starts, validate the project.

Detect things such as:

* missing entrance
* missing exit
* broken/disconnected route
* room not connected
* impossible path
* invalid timing range
* door not connected where expected
* duplicate IDs
* release rule references deleted object
* no way for first group to enter
* no configured way for subsequent groups to be released
* cyclic signal rules likely to create runaway events
* unreachable room
* background/scale problems that would prevent distance-based timing

Present errors and warnings clearly.

Do not simply crash.

## Simulation event log

Provide an optional event/log view useful for debugging.

Examples:

00:00.000 Simulation started
00:00.000 Group 1 released
00:03.421 Group 1 entered Cave
00:24.302 Cave timer completed for Group 1
00:27.110 Group 1 crossed Cave Exit Sensor
00:27.110 Entrance release signal generated
00:27.110 Group 2 released
...

Allow filtering by:

groups
rooms
doors
sensors
release events
warnings
flow failures

Do not allow the log UI to destroy performance during fast analytical runs; aggregate/buffer appropriately.

## Results persistence

Allow simulation results to be saved with the project or exported.

Each result should record enough context to reproduce/identify the run, including:

project/scenario
timestamp
simulation settings
random seed
duration
important metrics

Do not let stored historical results cause uncontrolled project-file growth.

## UI polish

This is a tool I will actually use.

Make basic editing comfortable.

Important behaviors:

* sensible cursor changes
* selection outlines
* handles for editing paths/doors
* hover feedback
* clear room labels
* visible direction of paths
* visible door swing/slide behavior
* smooth group motion
* readable property panel
* tooltips where useful
* status bar help
* confirmation before destructive actions
* unsaved-changes prompt
* normal error dialogs
* no giant cluttered modal windows when a dock/panel is more appropriate

The application should remain usable on a normal 1080p display.

## Performance

The visualizer does not need game-engine rendering, but it should feel smooth.

Do not tie simulation correctness to frame rate.

Fast analytical runs and optimization should not freeze the interface.

Use worker threads/processes or chunked execution where appropriate while keeping Qt thread-safety correct.

The user must be able to cancel long repeated/optimization runs.

## Architecture

Keep the code understandable.

Use a clear package structure inside `simulation`.

A sensible separation might include concepts such as:

* application/UI
* project persistence
* project/data models
* layout graphics/editor
* simulation engine
* events/rules
* analytics
* optimization
* tests

You may choose the exact filenames and architecture after inspecting the repository.

Do not create one enormous file.

At the same time, do not overabstract everything into dozens of pointless classes/files.

Favor readable Python.

Use type hints where useful.

Use dataclasses or similarly straightforward models where appropriate.

## Tests

Add meaningful automated tests for the non-GUI logic.

At minimum test:

* project serialization/deserialization
* project version handling
* room timing sampling
* group-size sampling
* path distance/travel calculations
* event ordering
* sensor trigger behavior
* entrance release-rule behavior
* door state transitions
* room occupancy
* room-overstay detection
* interior blockage detection
* throughput calculations
* seeded repeatability
* scenario overrides
* optimization constraints
* validation of broken projects

Run the tests yourself.

Also launch/smoke-test the GUI enough to catch obvious import/startup failures.

## Documentation

Add a README inside `simulation` explaining:

* what the simulator does
* installation/dependencies
* how to launch it
* how to create a project
* how to import/calibrate a layout
* how to create rooms
* how to draw paths
* how to configure doors
* how to place sensors
* how to configure release rules
* how to run simulations
* how to interpret blockage/overstay analytics
* how to use scenarios
* how to use the timing advisor
* project file format at a high level

## Important usability example

The finished program must be capable of configuring the following entirely through the GUI, with no Python edits:

1. Create a new project.
2. Import an overhead PNG of the haunt.
3. Calibrate it using a known 8-foot wall.
4. Draw Entrance -> Room A -> Room B -> Room C -> Exit.
5. Draw the walking path connecting them.
6. Put swinging/sliding doors between appropriate areas.
7. Configure Room A for roughly 20 seconds.
8. Configure Room B for roughly 27 seconds.
9. Configure Room C for roughly 18 seconds.
10. Place a virtual sensor after Room A.
11. Configure:

WHEN a group crosses that sensor
THEN release/admit the next exterior group.

12. Start the first group at simulation start.
13. Run one simulated hour.
14. Watch groups physically progress along the drawn route.
15. If Group 2 reaches an interior door while Group 1 is still blocking the next room, visibly flag the failure rather than treating it as a normal queue.
16. Open Analytics.
17. See groups/hour, guests/hour, room utilization, overstays, internal flow failures, and bottleneck explanations.
18. Run repeated simulations.
19. Ask the Timing Advisor for room-timing improvements.
20. Save the project and reopen it later with the background and configuration intact.

## Definition of done

Do not stop after creating an architecture or partial UI.

The task is complete when there is a functioning end-to-end application in the repository that can:

* create projects
* open/save projects
* import a background
* calibrate scale
* visually create/edit the haunt model
* configure rooms
* configure paths
* configure doors
* configure sensors
* configure event/action rules
* perform event-driven group admission
* visually simulate groups through the haunt
* detect internal flow failures
* calculate analytics
* compare scenarios
* run repeated simulations
* perform timing recommendations
* save/reload the work
* pass the non-GUI test suite

When you finish, review your own implementation for incomplete buttons, unconnected menus, TODOs, placeholder logic, or controls that visually exist but do nothing. Finish those before considering the task complete.

Then give me a concise summary of:

* what you created
* important architectural choices
* files added/changed
* dependencies
* how to launch it
* tests run and their results
* any genuine limitations that remain

Do not merely tell me what you would build. Build it.
