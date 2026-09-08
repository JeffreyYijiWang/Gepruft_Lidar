# ADR 0001: Pure protocol, one device owner, explicit hardware consent

Accepted 2026-09-06. Python 3.12, asyncio, pyserial, FastAPI, plain JavaScript Canvas.
The framing and protocol packages have no application dependencies. One state machine owns
one transport and serializes commands, requiring ACK plus the matching complete response.
Bounded subscriber queues protect acquisition from slow browsers. Simulation and replay
exercise the same parser and scan decoder as hardware.

Physical devices default to status-only. The operator must acknowledge the connector,
serial-standard, jumper, and voltage checks before configuration or streaming. No power
control exists. Persistent configuration uses read/modify/write/readback and skips equal
values. Never overwrite field/threshold settings with a canned configuration telegram.

Only standard full scans in documented 13-bit modes 00/01/02 are decoded. Configuration
selects mode 02 (distance plus field A/B/C), mm or cm. Reserved legacy mode 0D, reflectivity-only,
interlaced scans, and wider distance encodings are rejected rather than misinterpreted.
The old quick manual uses mode 0D; the newer listing marks it reserved. See PROTOCOL.md.

Explicit length profiles resolve manual discrepancies: B1 data is 146 bytes from Table 7-33
or 152 bytes from Table 7-34/SICK Toolbox, configuration is 32/34 bytes, and optional indices
extend the maximum 401-point telegram to 814 bytes. Unknown lengths fail closed. The six
reserved B1 bytes are corroborated by maintained driver source, not invented field meanings.
Recorder tasks capture their own recorder/queue at creation; immediate stop cannot invalidate
worker startup. Replay rejects truncation and index/raw disagreement.

Update this ADR and AGENTS.md together when changing these decisions.

## First physical status exchange

`probe-status` is a deliberately bounded native commissioning command outside the streaming
state machine. It reuses the pure command/framing/CRC/status decoders, but has only port and
new transcript-path arguments. It opens RS-232 at 9600 8-N-1, clears stale input, transmits
one `31`, requires ACK plus B1, then closes without a cleanup telegram. It never loads
environment settings, retries, searches baud, or requests BA/F4. This provides the narrower
operation required by the first physical test without changing ordinary probe/stream behavior.
The ordinary read-only `probe` reads status, type, and configuration; it is not a one-command probe.
Only the native Windows host owns a Keyspan COM port. Docker deployments continue to use
the separate native bridge; this bounded test can run directly in the host Python environment.

## Explicit opt-in original LMSAPI experiment, 2026-09-07

The operator requested a separate original LMSAPI backend and explicitly authorized its
configuration-on-connect and automatic retry behavior after reading the audit. This is a
scoped exception to the preceding commissioning restrictions, not a change to production
defaults. `lms200.lmsapi_experiment` runs the original x86 DLL in its own native Windows
process, owning COM7 exclusively, with operator power/startup gates and process watchdogs.
It retains the library's `80`-only parser and unreliable write-count semantics, labels
unavailable raw wire/ACK evidence honestly, and adds no outer retry or continuous scanning.
It does not enter the production state machine or normal transport selection. See
[LMSAPI_EXPERIMENT.md](../LMSAPI_EXPERIMENT.md) for parameters and bounded execution.

## Explicit native C++ bounded scan experiment, 2026-09-07

The operator subsequently requested a separate direct-Win32 C++ diagnostic and
authorized status, optional 100-degree/1-degree variant, continuous output for ten
seconds after start confirmation, and stop. This exception applies only to
`tools/lms200_native`; production Python defaults and transport ownership remain
unchanged. Fresh powered-on, startup-complete, other-COM7-applications-closed, and
optional-variant confirmations are required before its live invocation. No wiring
change is requested. One exclusive COM7 handle at fixed 9600/8-N-1 owns a persistent
reader and logs raw bytes before parsing, with no RX purge. At most three entirely
silent status attempts are allowed; other commands are not retried. An uncertain
start triggers one bounded cleanup stop, with ambiguity reported because both
start and stop return A0. See the [native diagnostic README](../../tools/lms200_native/README.md).

The subsequent access-denied investigation separates optional Windows serial
observations from actual read completion: unavailable diagnostic fields are null,
and failed status queries cannot mask read errors or fabricate successful drain.
An explicit native `--listen-only` option opens the same bounded ten-second raw
listener without any transmitted command. It cannot be combined with the variant
option. The normal status/ACK/reply requirements before streaming remain in force.

## Explicit ROS 2 status experiment through Windows, 2026-09-08

The operator selected a guarded ROS 2/SickToolbox status test through the working
Windows driver after current checks confirmed WSL lacks Keyspan kernel support.
`tools/ros2_status` is a separate ROS 2 diagnostic using the pinned LaViRIA library's
message serialization, CRC and checked send method. One native Windows process
owns COM7; anonymous pipes and a WSL PTY carry the bytes to/from the ROS process.
The unmodified LaViRIA scanning node and its installation remain preserved.

This experiment sends exactly one status request after separately confirmed
power-on/startup and at least 65 seconds. Both sides preserve raw bytes before
parsing and retain fragmented frames. The Windows gate rejects any other command
or repeat. No library initialization, baud search, configuration, continuous scan
or cleanup telegram is allowed. Physical write/flush evidence comes from Windows;
PTY counts alone are not scanner-transmission evidence. Production defaults stay
unchanged. See `tools/ros2_status/README.md` for build checks, gates and bounds.

The subsequent sequential Python/C++/ROS 2 comparison adds an explicit
already-powered-on checklist option to the ROS 2 wrapper. It still requires both
readers before the one status request, but uses the operator's pre-run completed
startup confirmation instead of requesting another power cycle or fabricating
marker files. The original OFF/passive-startup path and its 65-second gate remain
unchanged. Each selected backend owns COM7 for its whole run and releases it before
the next; this is not a shared physical handle across backends. Only the existing
native C++ sequence may perform the selected 100°/1° and bounded scan/stop stages,
with its existing status/ACK/reply gates. Production defaults remain unchanged.
