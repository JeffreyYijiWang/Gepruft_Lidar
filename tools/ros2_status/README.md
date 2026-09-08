# Supervised ROS 2 / LaViRIA status experiment

This is the Windows-bridge route explicitly selected on 2026-09-08. It runs a
project-owned ROS 2 node using the installed, pinned LaViRIA `SickLMS` and
`SickLMSMessage` library. It is **not the unchanged LaViRIA scanning node**.
The latter still has automatic baud fallback, incomplete-frame/header defects
and a no-op stop service; see `docs/SICKTOOLBOX_READINESS.md`.

Data path: Windows COM7 → anonymous pipes → WSL PTY → ROS 2 diagnostic. The reverse
direction admits exactly one complete binary status packet. No TCP listener,
USB attachment, Linux Keyspan driver, Docker, kernel changes or physical rewiring
are needed. The original third-party sources and `.local/laviria_lms200` stay unchanged.

## What runs

* `src/lms200/ros2_status_experiment.py` owns the only physical COM7 handle at
  9600/8-N-1, no flow control, DTR/RTS false. It logs every read before parsing;
  checks the seven-byte Windows write and bounded output flush; and captures at
  least five seconds after that flush. Partial frames survive empty reads.
* `pty_relay.py` owns a Linux pseudo-terminal and relays bytes over anonymous pipes.
  Hex is just its JSON transport encoding; the physical write receives binary bytes.
* `src/status_node.cpp` creates a ROS 2 node, opens the PTY once, and uses the original
  library's `BuildMessage` and inherited `_sendMessage(message, 0)` for one status.
  Its persistent reader validates available length/bounds before invoking the
  library's CRC generation with the actual 80/81 address. It recognizes standalone
  ACK/NAK and B1 payload lengths 148/154. This diagnostic does not decode all B1
  fields through the legacy driver's initialization path. Windows independently
  decodes a supported B1 using the project parser.

It never calls `Initialize`, `_getSickStatus`, `Uninitialize`, the old monitor,
scan methods, scanner baud setters, configuration or reset routines. Cleanup
closes the owned descriptors and child processes without sending a stop telegram.
No streaming is started. A successful ROS result needs ACK and a valid B1; the
combined result also needs the Windows capture to validate that response.

## Offline checks

```powershell
wsl.exe -d Ubuntu-24.04 -- bash /mnt/c/Users/Jeffr/OneDrive/Documents/GitHub/Gepruft_Lidar/tools/ros2_status/build-wsl.sh
wsl.exe -d Ubuntu-24.04 -- python3 /mnt/c/Users/Jeffr/OneDrive/Documents/GitHub/Gepruft_Lidar/tools/ros2_status/integration_check.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_ros2_status_experiment.py
```

The build verifies the original SDK/source hashes, compiles into
`tmp/ros2-status-build`, installs under ignored `.local/ros2_status`, and executes
only the no-port C++ self-test. `integration_check.py` runs the real ROS diagnostic
against synthetic scanner bytes through a PTY, covering both response addresses
and 600 ms gaps. It never opens a physical serial port. Synthetic logs stay under
`tmp/ros2-pty-offline-*`, not the physical capture directory.

`build-evidence.json` contains UTC build time, file sizes and SHA-256 for source
inputs, the installed SDK and the new executable. The Windows owner checks these
before it can open COM7. Rebuild after changing a recorded input.

## Supervised physical run

For an already powered-on scanner, explicitly confirm completed startup, unchanged
direct wiring/no jumpers and closed competing COM7 applications. The separate
`--confirm-powered-on-direct-checklist` flag replaces the OFF flag below:

```powershell
.\.venv\Scripts\python.exe -m lms200.ros2_status_experiment --run `
  --confirm-powered-on-direct-checklist --log-dir docs/diagnostics/NEW-ros2-status
```

This mode records `already_powered_on`, waits for both readers to be ready, then
allows the same single status packet. It does not claim a captured power-on or
create power/startup acknowledgment files, and it does not wait another 65 seconds.
The two checklist flags are mutually exclusive. A pre-run startup confirmation
is required; the program cannot determine power or LEDs itself. All packet,
write/flush, receive-duration and cleanup restrictions remain the same.

For a passive startup capture, use the original OFF workflow:

Require explicit operator confirmation of scanner OFF, direct Keyspan→LMS200
RS-232 data connection, normal connector fit, no jumpers/open scanner pins 7–8,
and other COM7 applications closed. Use a new directory under `docs/diagnostics`:

```powershell
.\.venv\Scripts\python.exe -m lms200.ros2_status_experiment --run `
  --confirm-off-direct-checklist --log-dir docs/diagnostics/NEW-ros2-status
```

Wait for `listener.ready` and the `both_listeners_ready` event. Only then ask the
operator to turn the scanner ON. Write `power-on.confirmed` only after that explicit
reply, and `startup-complete.confirmed` only after confirmation that yellow is OFF
with green or red alone. These are operator acknowledgments, never timers pretending
to be physical confirmation. The controller waits at least 65 seconds from the
power-on acknowledgment AND startup completion before creating `status.trigger`.

The ROS node generates one `02 00 01 00 31 15 12` packet. The Windows gate rejects
early TX, different commands, appended bytes and retries. It writes and flushes
only the complete accepted packet. The ROS reader runs for six seconds after its
send, while the Windows reader independently enforces at least five seconds after
physical-driver flush. PTY write/drain results alone do not establish Windows
driver transmission, and Windows counts still do not measure electrical signals
at the scanner connector.

To cancel, create `cancel.trigger` in this run directory or interrupt the Windows
controller. Power-on preparation is bounded to 300 s; startup acknowledgment to
300 s after power-on; the entire experiment to 660 s. Child cleanup has additional
short time bounds. No next run is queued.

Evidence: `windows-raw.jsonl`, `windows-result.json`, `ros2-events.jsonl`,
`ros2-console.log`, archived build manifest and explicit operator marker files.
Windows pyserial purges buffers during initial open; there is no purge/reopen
after the listener-ready event or after scanner power-on.
