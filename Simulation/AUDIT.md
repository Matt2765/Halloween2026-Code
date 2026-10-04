# HauntSim audit — October 4, 2026

## Result and scope

Audited the standalone simulation in Halloween2026 and HalloweenTemplate: model, validation, event engine, metrics, repeated simulations, timing advisor, desktop workflows, portable project persistence, and Nextcloud transport/cache. Both installations receive identical simulation changes. Hardware-control code under MainCode is outside this audit.

The duration selector now describes the settings that actually run. Presets use 600, 1800, 3600, or 7200 seconds and stop on time. Custom uses its stored duration, stop condition, and completion target. Selecting a preset retains the custom values; selecting Custom restores them in the settings window. Cancel restores the preceding selection. Project loading, scenario switching, settings edits, and undo refresh the selector. Run controls lock the selector during execution.

## Findings fixed

| Finding | Effect before correction | Correction |
| --- | --- | --- |
| Stale duration selector | Displayed duration could disagree with loaded project or edited settings | Refresh selection from effective scenario settings |
| Custom settings overwritten by presets | Switching back to Custom could lose the previously configured run | Retain custom duration, stop condition and limit in portable settings |
| Event stepping past the end time | Stepped results could include events beyond the configured horizon | Enforce the same time boundary in stepping and animation |
| Animated run paused with an empty event queue | A time-based run could stop advancing before its requested duration | Continue the simulated clock to the horizon |
| Bent-path spacing calculated from a diagonal | Real collisions could be missed and false collisions reported | Split closest-approach calculations at each polyline corner |
| Disabled selected outgoing path still traversed | A group could leave a room onto a path disabled by a rule | Hold it in the room until its selected path is enabled |
| Incomplete numeric and structural validation | NaN, infinity, malformed objects, invalid capacities, or invalid route directions could crash or distort a run | Validate structure, finite numbers, stop conditions, geometry, references, and integer counts |
| Extra throughput bucket at the final boundary | A completion at exactly the horizon was placed in a new interval outside the run | Include the final endpoint in the last interval; record interval end times |
| Percentile estimates rounded downward | With two observations, the reported 95th percentile was the minimum | Use linear interpolation between ordered observations |
| Reports shared mutable engine data | Changes to exported report dictionaries could alter engine state | Return independent report snapshots; extend occupancy charts to the end time |
| Old timing advice could apply to a changed project | Recommendations could be applied to a different scenario or edited configuration | Associate each recommendation with its source and reject stale applications |
| Stopped visual runs could resume or duplicate stored results | Controls could extend a stopped run or append its result repeatedly | Require Reset/Edit and collect each visual result once |
| New remote save reported as up to date | An open project retained its old version while cloud status appeared current | Report that a new version is available and preserve the active edit's base version |
| Corrupt remote project blocked valid projects | A malformed file could abort the whole folder download | Isolate invalid files, report them, and continue caching valid projects |
| Corrupt remote version blocked conflict recovery | Local work could stay pending behind an unreadable competing file | Preserve local work in a separate conflict copy |
| Opening a project refreshed unrelated files | An unrelated remote error could prevent retrieving the selected project's newest save | Refresh the selected project directly |
| Cloud listings repeatedly loaded all project blobs | Large folders caused unnecessary memory use and repeated database reads | Use metadata-only listings and a name lookup map |
| HTTP error response handles left open | Repeated connection failures could retain resources | Close response handles before propagating errors |

## Verification

The complete suite contains **79 automated tests** per installation, including the existing engine, GUI, persistence, and analysis tests. New checks exercise:

- Independent arithmetic: a five-second entrance path, ten-second room scene, and five-second exit path finish at twenty seconds; a sixty-second run yields sixty groups/hour and 240 guests/hour for one completed four-person group.
- Partial journeys: at eight seconds, five walking seconds and three scene seconds have elapsed, with no completed group.
- Saturated pipeline: completions at twenty, thirty-five, and fifty seconds; exact walking, scene, and blocked totals.
- Downstream contention: two groups finish at twenty and thirty seconds, including exactly five seconds of interior blockage.
- Agreement between headless, stepped, and animated time boundaries; backwards-time rejection; stopped-run controls.
- Real corner collisions and absence of false diagonal collisions on bent paths.
- Final-endpoint throughput buckets, immutable reports, interpolated percentiles, and stale-advice rejection.
- Duration presets, restored custom settings, cancel, scenario selection, undo, and project save/reload.
- **100 reproducible generated simulations** with varied room durations, capacities, path times, calibrated travel, walking speeds, seeds, run lengths, and exterior supply. Each checks guest/group conservation, walking + scene + blockage time against total time inside, capacity bounds, single-group path occupancy, room utilization bounds, valid event times, and interval completion totals.
- A local HTTP WebDAV fixture exercises actual upload/list/download requests, required headers, Unicode and reserved filename characters, version conditions, remote deletion, corrupt files, conflict recovery, active remote updates, and normalized dates.
- Durable offline recovery, retry after lost upload acknowledgement, simultaneous edits, and saving a newer revision during upload.

No requests or changes were made to the live Nextcloud server during this audit because it was undergoing maintenance. The previous implementation's live connectivity check passed before that maintenance; the current changes were verified using the local WebDAV fixture.

## Interpretation and remaining limits

No unresolved failures remain in these checks. An audit and passing tests do not prove that all possible inputs are bug-free. Simulation accuracy also depends on realistic scene timings, walking-speed ranges, scale or path travel overrides, release rules, branch weights, and door configuration.

The model moves indivisible groups, allows one group on a path at a time, and measures room capacity in groups. Spacing checks predict point-group proximity in layout pixels; they do not model individual bodies, crowd dynamics, or evasive motion. Completion targets can exceed a guest target by the last whole group's size. Repeated-run percentiles describe the sampled runs, not guaranteed real-world bounds. Timing advice remains a bounded local search and should be checked with repeated runs.

Cloud behavior is sync-on-save, with durable offline queues and conflict copies. It does not merge simultaneous edits or replace an open layout silently. Server changes and outages after this audit may need a fresh connectivity check once maintenance completes.
