# Project instructions for Codex

## DEBUG_INFO semantics

The user defines `house.DEBUG_INFO` in `MainCode/house_state.py` as the switch for
extra troubleshooting information needed while diagnosing or fixing problems.

- Gate verbose diagnostic logs behind `DEBUG_INFO`: detailed command traces,
  radio counters, timing details, telemetry-recovery traces, and similar debugging output.
- `DEBUG_INFO = False` must leave normal operational events, meaningful errors,
  and live status displays available. It is not a global logging or output switch.
- `DEBUG_INFO = True` adds troubleshooting detail. It does not enable hardware,
  alter control behavior, or replace separate settings such as `DEBUG_BREAKCHECK`
  and `DISABLE_REMOTE_SENSOR_MONITOR`.
- Follow these semantics when adding or changing debug output anywhere in the project.
- Pass the configured value explicitly to worker processes when needed. The RSM
  worker currently receives it at startup, so changing the configuration requires
  restarting the application.
- ESP32 USB diagnostics are separate from the Python setting. Do not claim that
  `house.DEBUG_INFO` controls firmware output without implementing that connection.
