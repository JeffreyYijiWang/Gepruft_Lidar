# Architecture

## Layers and ownership

```text
serial / TCP bridge / replay / simulator
                  │ byte stream
                  ▼
        Framer + LMS CRC (pure Python)
                  │ Frame or ACK/NAK
                  ▼
        typed responses + measurement decoder
                  │
        Device state machine (one reader, one command at a time)
                  │
        Service → bounded WebSocket subscribers → Canvas dashboard
                  └→ bounded recorder queue → binary / JSONL / exports
```

`protocol/` contains only byte construction, framing, CRC, response validation, and geometry.
It imports neither FastAPI nor pyserial. `transports/base.py` defines dependency injection:
`open`, `read`, `write`, `set_baud`, `close`, current baud and baud-change capability.
An empty read is an idle interval; `EOFError` is disconnection. Serial blocking operations
run in bounded worker-thread calls, TCP uses asyncio streams, and replay/simulation share
the normal parser. `state_machine.py` owns the single reader and serializes commands.

States cover disconnected, opening, detecting baud, connected, requesting status,
installation, configuring, changing baud, verifying, starting, streaming, recovering,
stopping, and faulted. An explicit reconnect performs recovery. Fault supervision stops
output when communication remains available and closes the transport; it does not keep
rewriting configuration automatically. An unconfirmed stop leaves a diagnostic warning.

The service gives each browser a two-scan queue, replacing old scans for slow clients.
Recording has a 128-scan queue and a file worker. Diagnostics distinguish frame CRC/length
errors, malformed scans, timeouts, telegram-index gaps, client queue drops, and recording
queue drops. Telegram index gaps are modulo 256; losses of exactly 256 telegrams cannot
be distinguished. Without indices, exact dropped-scan counts are unavailable. Serial
bandwidth limiting scanner output is not itself a detected missing telegram.

## Bridge and baud control

Windows/macOS Docker Desktop runs Linux in a VM. Use a **native** bridge process to own
the host COM or tty device. Linux may use either native serial mapping or this bridge.

The default data endpoint is TCP 7000 and control endpoint is TCP 7001. Both belong to
one native bridge, use no LMS-specific parser, and are independently configurable.

1. Client opens control, sends a JSON line `{"op":"lease","token":"…"}`.
2. Bridge verifies the token, permits one lease, and opens the data listener. Reply is
   `{"ok":true,"data_port":7000,"baud":9600}` (port can be ephemeral when configured as 0).
3. Client opens that data port from the same peer IP. Only one connection is admitted;
   the listener closes. All bytes in both directions are passed through unmodified.
4. After receiving the scanner's ACK and full baud-change A0 at the old baud, the client
   sends `{"op":"baud","baud":38400}` on control. The bridge sets **host pyserial baud**
   and replies `{"ok":true,"baud":38400}`. The protocol service then verifies scanner status.
5. Closing control releases the lease and data connection. A connection may need a new
   lease after interruption. The bridge never sends the LMS stop command on its own.

`{"op":"status"}` reports the bridge's current adapter baud. Invalid requests receive
`{"ok":false}`; JSON lines are bounded to 4096 bytes. Tokens never appear in LMS bytes or logs.
The token and peer-IP checks are practical local protections, not TLS or a defense against
hostile processes sharing the same host/IP. Only one trusted controller may use the bridge.
For nonlocal networks use an encrypted tunnel and explicit firewall rules.

Loopback is the default bind address. Binding `0.0.0.0` requires `LMS_BRIDGE_TOKEN` and the
control channel. Docker Desktop needs a host address reachable from the VM. Allow only
the local Docker environment through the firewall. Linux Compose bridge mode supplies
`host.docker.internal:host-gateway`.

Third-party fixed-baud transparent bridges work without `--control-port`; set their host
adapter baud separately and use `--fixed-baud --baud RATE`. The app refuses a different
target baud without control. Changing an integer in a container does not change a host adapter.

500000 is supported only with `--high-speed --serial-standard rs422` and jumper confirmation.
Native serial and the bridge pace outgoing host bytes at 100 µs using writes/flush/sleep,
following the manual's 55 µs minimum. General-purpose OS/USB scheduling cannot guarantee
the maximum 6 ms interval under load. Loopback and simulator tests validate the software
sequence, not real line timing, adapter custom-divisor behavior, or sustained scanner traffic.
Use 9600/38400 for initial commissioning. Legacy card divisor aliases in Quick Manual p17
are not universal baud values and are never applied to modern adapters.

## Safety and persistent settings

Read-only is the physical default. Before mutations, the application requires explicit
power/data connector identification, selected serial standard, suitable voltage levels,
and an RS-422 jumper confirmation. Host discovery changes only adapter settings; probes
send read requests. The application does not provide reset, laser power, output switching,
firmware update, calibration, or field-writing commands.

Configuration is read/modify/write/readback. The app changes only angular variant, distance
mode 02, unit, and the real-time-index bit. All other configuration bytes are retained;
equal values skip writes. The manual warns that parameter writes consume EPROM cycles.
Mutating requests have one attempt, because a missing reply does not prove the write failed.
Idempotent reads get at most three attempts. See [Protocol](PROTOCOL.md) for exact sequencing.

## Recording and exports

Each recording has four same-stem files:

| File | Contents |
| --- | --- |
| `.bin` | Unmodified, CRC-validated received B0 telegrams concatenated in order |
| `.metadata.json` | Format `lms200-raw-v1`, scanner ID/status, physical baud, verified raw config, coordinates |
| `.index.jsonl` | One entry per raw telegram: byte offset, byte length, receive timestamp, application sequence |
| `.jsonl` | Optional interpreted scans, each including metadata and original telegram hex |

Raw recording is a scan-telegram record, not a bidirectional packet capture: it excludes
commands, passwords, ACK bytes, and discarded noise. The original binary data for every
recorded decoded scan is retained. Stop recording before copying the files as a set.
Use a named volume or an existing writable bind mount owned by UID 10001 in containers.

Replay requires metadata, validates its format, and fragments reads into at most 137 bytes.
With the index, original receive timestamps and spacing are retained (scaled by replay speed).
Without it, raw telegrams are read as fast as possible and receive new timestamps.
Sequence numbers are local to each acquisition/replay run. Replay never sends scanner commands.
An incomplete trailing telegram or disagreement between the raw file and timing index faults
replay instead of reporting completion. The recording worker owns its recorder and queue so
an immediate stop cannot invalidate its resources; write failures are reported and a later
recording may start with a new file set.

JSON exports include complete scan/raw/point data. CSV starts with a `# metadata=...` line,
then point rows; use a CSV reader configured to skip comments. PCD v0.7 ASCII retains point
count with NaN coordinates for invalid returns and a `valid` field; metadata is in a comment.
Coordinates are metres in the top view: +x right, +y forward, angles increase counterclockwise.
All files carry enough scanner configuration to interpret distance units and flags.

## REST and WebSocket interface

| Endpoint | Behavior |
| --- | --- |
| `GET /health` | 200 when service is alive without a device fault; 503 for faulted state |
| `GET /api/status` | State, counters, verified configuration, rates, redacted log |
| `GET /api/ports` | Serial ports visible to the service's OS (container cannot enumerate host COM ports) |
| `POST /api/action` | `{"action":"probe|start|stop|reconnect"}`; 202 for accepted asynchronous action |
| `POST /api/consent` | HardwareConsent booleans plus `enable_writes`; physical mutation gate |
| `GET /api/scans/latest` | Latest decoded scan |
| `GET /api/export/json`, `/csv`, `/pcd` | Download latest scan |
| `POST /api/record/start`, `/stop` | Start/finalize recording |
| `GET /api/recordings`, `/api/recordings/{name}` | List/download contained recording files |
| `WS /ws/scans` | `{type:"scan",data:...}` and `{type:"status",data:...}` messages |

OpenAPI is available at `/docs`. API errors and device status must be checked separately:
an accepted action is not proof the device completed it. No public service authentication
is provided; native and published container ports bind loopback. Host and Origin checks
prevent ordinary cross-site browser control. Use a separate reviewed security boundary
before exposing the API beyond the local machine.

## Platform and protocol limits

Standard complete scans only: 180° at 1°/0.5°, 100° at 1°/0.5°/0.25°. Measurement
modes 00/01/02 have documented 13-bit distances; configuration selects 02. Interlaced,
reflectivity-only, 14/15-bit distance modes and special variants are rejected. Status layouts
are explicitly bounded; unknown firmware layouts are not guessed. Model detection does not
certify the product label or electrical wiring. Linux PTY and Windows native loopback are
automated; native macOS and real LMS200 behavior still require commissioning.
