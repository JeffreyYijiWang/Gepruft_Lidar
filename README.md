# Gepruft Lidar — LMS200 Scan Station

Python 3.12 acquisition, recording, replay, and a local browser dashboard for the
**SICK LMS200-30106 (1015850)**. The default container runs a fragmented-byte simulator.
Physical connections are read-only until the operator confirms the wiring checklist.

## Project progress — September 8, 2026

**The software and diagnostic tools are built; a valid reply from the physical
LMS200 has not yet been established.** The latest completed Python, native C++,
and guarded ROS 2 comparison recorded zero incoming bytes in all three methods.
No ACK/NAK, CRC-valid scanner response, or real scan data was obtained. The cause
remains unresolved.

The [project wiki](WIKI.md) contains the development timeline, communication paths,
results, evidence links, known limitations, and next steps. It is the detailed
progress record; this README keeps the current overview and setup instructions.

| Area | Progress | Evidence / details |
|---|---|---|
| Application | Protocol, simulator, recording/replay, CLI and browser dashboard implemented; simulator demonstrations are documented separately from hardware trials. | [Implementation report](docs/IMPLEMENTATION_REPORT.md) |
| Windows diagnostics | Fixed-9600 raw capture, persistent receive workers and explicit write/flush/response evidence added. Diagnostic-query failures are separated from read failures. | [Native C++ diagnostic](tools/lms200_native/README.md), [reader-fix result](docs/diagnostics/native-reader-fix-COM7-20260907T054336Z/SUMMARY.md) |
| LaViRIA imports | Exact C++ SDK and ROS 2 package compiled and installed under `.local/laviria_lms200`; source and artifact hashes recorded. Upstream live-use defects remain documented. | [Package setup](tools/sicktoolbox_offline/README.md), [readiness review](docs/SICKTOOLBOX_READINESS.md) |
| ROS 2 through Windows | A separate guarded status diagnostic connects ROS 2 through a WSL PTY/pipes to one Windows COM7 owner, avoiding a direct WSL Keyspan dependency. | [ROS 2 diagnostic](tools/ros2_status/README.md) |
| Physical communication | Port opens and driver-accepted status writes are recorded. Valid scanner replies and continuous scans remain unverified. | [Latest comparison](docs/diagnostics/method-comparison-COM7-20260908T183745Z/SUMMARY.md) |

The latest comparison used the operator-confirmed direct RS-232 connection,
Keyspan USA-19HS on COM7, 9600/8-N-1, and sequential exclusive port ownership:

| Method | Status requests / OS-reported TX | Recorded reply window | RX |
|---|---|---|---|
| Python diagnostic | 1 / 7 bytes | 5.000 s after flush | 0 bytes |
| Native Win32 C++ | 3 / 21 bytes | 5.024 / 5.023 / 5.020 s after drain | 0 bytes |
| Guarded ROS 2 via Windows | 1 / 7 bytes | Windows: 6.110 s after flush; ROS 2: 6.032336 s after send | 0 bytes |

All three completed and closed their port handles. The requested 100°/1° variant
and continuous/start/capture/stop stages were not reached because the status
exchange failed. These driver-level results do not prove electrical transmission
or identify a cable, adapter, settings, or scanner fault. Earlier passive captures
did contain unclassified binary bytes; the complete history is in the wiki.

The next milestone is one raw, CRC-valid and semantically valid status exchange
before continuous acquisition. Use the current guarded diagnostic procedure and
fresh physical confirmations for another connected test. This documentation update
did not run hardware or queue another test.

## Start the simulator

```sh
docker compose up --build -d
docker compose ps
docker compose logs --tail 30
```

Open [Scan Station](http://localhost:8000). The dashboard starts receiving synthetic
181-point scans at about 2.6 scans/s at the simulated 9600-baud rate. Use **Record**,
**Finish recording**, and the download links to preserve scans. **Stop** returns the
device to output-on-request mode; **Reconnect** runs initialization again.

```sh
docker compose stop
```

Recordings live in the named `gepruft_lidar_recordings` volume and survive container
replacement. `docker compose down` keeps them; adding `-v` deletes volumes and recordings.

## Native installation

Use Python 3.12 or later (3.12 is the tested baseline). A virtual environment is recommended.

```sh
python -m venv .venv
# Linux/macOS: . .venv/bin/activate
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install -c requirements.lock -e '.[dev]'
lms200 serve --transport simulator --autostart
```

No browser build step, CDN, or external account is required. The native web server binds
`127.0.0.1:8000`; Compose publishes the container only to host loopback.

## Physical scanner: prerequisites

An ordinary USB-C data cable cannot connect to this scanner. Provide a regulated
**24 V DC ±15%, at least 2.5 A** supply, the correct power connector/cable, a USB-to-RS-232
or four-wire RS-422 adapter with its **host driver installed**, and the correct data cable.
Power/I/O and data are separate 9-pin connectors. Never route 24 V into USB or a serial adapter.
This scanner is **not a certified machine-safety protective device**.

Read [hardware and wiring](docs/HARDWARE.md) before connecting. In particular, the corrected
data pinout is pin 3 = TD+/TxD and pin 4 = TD−. The older RS-422 numeric crossover is wrong.

1. With power off, identify both connectors and verify cable continuity and adapter voltages.
2. Wire RS-232 TX↔RX/GND, or RS-422 TX±↔RX± by signal name; bridge scanner data pins
   7–8 only for RS-422.
3. Connect the serial adapter with its host driver, then apply the external 24 V supply.
4. Wait for startup: yellow + red means initializing; green alone or red alone means
   communication-ready. Allow up to 60 seconds. Red alone can indicate a monitored-field
   infringement; it does not by itself prove a communication fault.
5. List ports, then run a read-only probe:

   ```sh
   lms200 ports
   lms200 probe --transport serial --port /dev/ttyUSB0
   # Windows: replace /dev/ttyUSB0 with COM3.
   # macOS: use /dev/cu.usbserial-XXXX.
   ```

6. Follow [Windows](docs/WINDOWS.md), [Linux](docs/LINUX.md), or [macOS](docs/MACOS.md).
   Docker Desktop uses the native host bridge; Linux supports direct device mapping.
7. After the checklist, start the stream. Example native RS-232 configuration:

   ```sh
   lms200 stream --transport serial --port /dev/ttyUSB0 --target-baud 38400 \
     --angle 180 --resolution 1 --unit mm --allow-writes --confirm-hardware \
     --duration 10 --output scan.jsonl
   ```

   `--confirm-hardware` explicitly confirms all four connector/standard/voltage checks
   above. RS-422 also requires `--serial-standard rs422 --confirm-rs422-jumper`.
   The dashboard offers the equivalent individual checkboxes.
8. Stop with Ctrl+C, the dashboard **Stop** button, or `docker compose stop`. Wait for
   the log confirming `20/25` before removing power. An unconfirmed stop is reported.

## CLI

Optional C++ SickToolbox and ROS 2 LMS200 builds are prepared separately:
[offline build results and live-use limitations](docs/SICKTOOLBOX_READINESS.md).
No scanner program was launched during that preparation.

| Command | Behavior |
| --- | --- |
| `lms200 ports` | Enumerate native serial ports; select a port explicitly if more than one exists |
| `lms200 probe-status --port COMx --log NEW.jsonl` | One native RS-232 status request at fixed 9600 8-N-1; raw hex/CRC transcript; no baud search or additional requests |
| `lms200 probe`, `status`, `diagnose` | Read B1 status, device ID, and configuration; no scanner writes |
| `lms200 configure` | Initialize and verify requested settings, then leave output-on-request |
| `lms200 stream` | Initialize, decode scans, print JSONL or use `--output` |
| `lms200 record` | Record binary telegrams, metadata, timing index, and decoded JSONL |
| `lms200 replay --file PATH.bin` | Decode recordings without sending any commands |
| `lms200 serve` | Local REST/WebSocket service and dashboard |

`--baud` sets the initial/fixed connection setting; `--target-baud` explicitly requests a
scanner/adapter change after discovery. Detection tries 9600, 38400, 19200; `--fixed-baud`
disables it. The 19200 rate is also documented, even though the initial hardware brief omitted it.
500000 requires explicit RS-422 opt-in and qualified hardware: [bridge/baud design](docs/ARCHITECTURE.md).
`--read-only`/`--probe-only` prevents mutations. Run `lms200 COMMAND --help` for all arguments.

```sh
lms200 record --transport simulator --duration 5
lms200 replay --file recordings/scan-YYYYMMDDTHHMMSS-NNNNNNZ.bin --replay-speed 2
```

Raw replay needs its same-stem `.metadata.json`; keep `.index.jsonl` to reproduce receive
timing. For Docker replay, put all files in `./recordings`, set `LMS_REPLAY_FILE` in `.env`, then:

```sh
docker compose -f compose.yaml -f compose.replay.yaml up -d
```

## Architecture and validation

* [Architecture, API, recording format and limitations](docs/ARCHITECTURE.md)
* [Command layouts, state sequence, CRC, vectors and manual corrections](docs/PROTOCOL.md)
* [Reference index and provenance](docs/references/README.md)
* [Troubleshooting](docs/TROUBLESHOOTING.md)
* [Implementation and verification report](docs/IMPLEMENTATION_REPORT.md)

```sh
python -m ruff format --check src tests tools
python -m ruff check src tests tools
python -m mypy
python -m pytest -q
docker build --target test -t gepruft-lms200:test .
```

The test build also exercises Linux serial access through a pseudo-terminal and the native
bridge through pyserial `loop://`. Physical tests are opt-in. Simulation demonstrates the
software path; cable wiring, firmware behavior, and high-speed timing still need real hardware.
