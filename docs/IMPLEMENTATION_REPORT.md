# Implementation and verification report

Verified September 6, 2026 (America/New_York), using Windows Python 3.12.14 and a Linux
Python 3.12 container under Docker Desktop. The application is running in simulator mode
at [localhost:8000](http://localhost:8000). No physical scanner was connected or configured.

## Delivered files

| Area | Files |
| --- | --- |
| Project/setup | `README.md`, `AGENTS.md`, `LICENSE`, `pyproject.toml`, `requirements.lock`, `.gitignore`, `.dockerignore`, `.env.example` |
| Pure protocol | `src/lms200/protocol/crc.py`, `framing.py`, `commands.py`, `responses.py`, `measurements.py`, package initializer |
| Transports | `src/lms200/transports/base.py`, `serial.py`, `tcp.py`, `replay.py`, `simulator.py`, transport factory initializer |
| Device/application | `src/lms200/config.py`, `state_machine.py`, `service.py`, `cli.py`, `bridge.py`, `recording.py`, `exports.py`, package initializer, `py.typed` |
| API/dashboard | `src/lms200/api/app.py`, API initializer, `src/lms200/web/index.html`, `app.js`, `style.css` |
| Native bridge entry point | `tools/serial_bridge.py` |
| Container | `Dockerfile`, `compose.yaml`, `compose.serial.yaml`, `compose.bridge.yaml`, `compose.replay.yaml` |
| Verification | `scripts/verify.ps1`, `scripts/verify.sh`, `tests/conftest.py`, `tests/fixtures/golden.json` |
| Test suites | `tests/test_crc.py`, `test_framing.py`, `test_commands.py`, `test_measurements.py`, `test_state_machine.py`, `test_simulator.py`, `test_bridge.py`, `test_api.py`, `test_config.py`, `test_posix_serial.py`, `test_hardware.py` |
| Documentation | `docs/FINDINGS.md`, `ARCHITECTURE.md`, `HARDWARE.md`, `PROTOCOL.md`, `TROUBLESHOOTING.md`, `WINDOWS.md`, `LINUX.md`, `MACOS.md`, this report, `docs/references/README.md`, two ADRs in `docs/adr/` |

The reference index includes source URLs, exact manual sections, corrections, access dates,
and hashes. Reference PDFs are excluded from the deliverable. Existing repository history
was preserved; no publication or remote push was performed.

## Architecture implemented

Serial, TCP bridge, simulator, and replay supply bytes to the same incremental framer and
LMS CRC implementation. Typed command builders are separate from reads and decoding. One
asyncio state machine owns the transport and permits one outstanding command. FastAPI and
the CLI share that device service. Bounded queues feed the Canvas WebSocket client and
the recording worker. JSON, CSV, PCD, raw binary, timing index, and decoded JSONL outputs
retain scanner configuration and coordinates.

The native bridge forwards data without parsing telegrams. A separate authenticated control
lease changes the physical adapter baud after the scanner's old-rate response. Linux supports
direct serial-device mapping; Docker Desktop on Windows/macOS uses the host bridge.
Physical writes require explicit wiring consent. Simulator and replay need no hardware consent.

The runtime container runs as UID/GID 10001, installs runtime dependencies only, has a health
check and mounted recording volume, publishes on host loopback, drops capabilities, and uses
a read-only root filesystem. Neither privileged mode nor USB host-driver installation is used.

## Exact scanner command sequence

Below are payload bytes; framing is `02 address lengthLE payload crcLE`. Each request requires
standalone ACK `06` **and** its matching validated response. Source tables, complete example
telegrams, CRC values, timeouts, and retry rules are in [PROTOCOL.md](PROTOCOL.md).

1. Open the host adapter at controlled candidates 9600, 38400, 19200; 500000 is explicitly
   gated. Send status `31`, require `B1`, and confirm the reported baud.
2. Send model/type `3A` → `BA`, then configuration read `74` → `F4`. A read-only probe ends
   here and sends no stop or configuration request.
3. After hardware consent and target-model validation, send stop/on-request `20 25` → `A0 00`.
4. When geometry or measurement settings need changes, enter installation with
   `20 00 53 49 43 4B 5F 4C 4D 53` → `A0 00` (default password `SICK_LMS`).
5. If baud changes, send `20 42` (9600), `20 41` (19200), `20 40` (38400), or `20 48`
   (500000). Require `A0 00` at the old baud, change the physical adapter, and verify `31`.
6. If geometry changes, send `3B angleLE resolutionHundredthsLE`, require `BB 01` and exact
   geometry echo. Example 180°/1° payload: `3B B4 00 64 00`.
7. If configuration changes, send `77` followed by the previously read 32/34 bytes with
   only the requested index bit, mode 02, and unit changed. Require `F7 01` plus exact echo.
8. Read `74` and `31` again; verify complete configuration, geometry, unit, and mode.
9. Send `20 25` → `A0 00` to leave installation in monitoring-on-request. `configure` ends here.
10. Send continuous output `20 24` → `A0 00`; decode validated complete `B0` scans.
11. On shutdown, send `20 25` → `A0 00` when communication remains available, report whether
    stop was confirmed, then close the transport. Ambiguous mutating requests are not retried.

Equal configurations skip persistent writes. Unknown status layouts and unsupported scan
modes fail closed. The documented status-table discrepancy is explicitly handled with
146/152-byte profiles; it is not assumed resolved for every firmware revision.

## Tests and build results

| Check | Observed result |
| --- | --- |
| Ruff format | 35 Python files already formatted |
| Ruff lint | All checks passed |
| mypy strict | No issues in 22 source files |
| Windows `scripts/verify.ps1` with Python 3.12 virtual environment active | **52 passed, 2 skipped**; hardware and POSIX PTY skipped |
| Linux `docker build --target test -t gepruft-lms200:test .` | **53 passed, 1 skipped**; physical hardware skipped; image built successfully |
| `docker compose up --build -d` | Runtime image built; service started successfully |
| Container shutdown | SIGTERM completed; log confirmed output-on-request `20/25` before disconnect |
| Runtime user | `uid=10001(scanner) gid=10001(scanner)` |
| Browser | Live Canvas scan and WebSocket status displayed; no browser warning/error logs observed |
| Recording/replay demonstration | 47 scans recorded in the container and replayed successfully by the CLI |

Tests cover vendor CRC vectors, fragmented/noisy/concatenated input, invalid lengths and CRCs,
ACK/NAK/timeouts, controlled baud detection, state transitions, configuration preservation,
180° and 100° scan geometry, measurement flags, bounded subscribers, immediate recording stop,
recording write-failure recovery, truncated replay/index disagreements, exports, and API/WebSocket
integration. Native bridge tests use pyserial `loop://`, enforce token/exclusive leases, and
exercise baud control. Linux additionally exercises pyserial through a POSIX pseudo-terminal.
High-speed tests verify software pacing and control sequencing only.

Both test runs emitted two upstream deprecation warnings from the Starlette test client:
its httpx integration and an AnyIO alias. These did not fail checks or affect the demonstrated
runtime. Native macOS was not available for execution.

To reproduce locally, activate the virtual environment from the README, then run:

```powershell
.\scripts\verify.ps1
docker build --target test -t gepruft-lms200:test .
docker compose up --build -d
docker compose ps
```

POSIX verification uses `sh scripts/verify.sh` with the virtual environment active.
Dependency versions in `requirements.lock` are installation constraints, not a requirement
to install development tools into the runtime image.

## Simulator demonstration

The default simulator produces fragmented telegrams for 181 points over 180° at 1° resolution
in millimetres. The dashboard measured about **2.56 complete scans/s** at simulated 9600 baud,
with zero observed CRC errors. It separately displayed the nominal 75 Hz mirror frequency
and serial throughput ceiling. This receive rate is deliberately constrained by serial capacity.

Browser controls created recording `scan-20260907T004458-062464Z` in `/data/recordings`.
Its binary file contains 17,578 bytes: 47 telegrams of 374 bytes. Metadata, timing index,
and decoded JSONL are present. The demonstrated replay command was:

```sh
docker compose exec -T lms200 lms200 replay \
  --file /data/recordings/scan-20260907T004458-062464Z.bin \
  --replay-speed 100 --output /tmp/lms200-replay-validation.jsonl
```

The replay output had 47 scan lines. `/tmp` output is disposable; the four recording files
remain in the named volume. The web download links provide copies to the host.

Docker Desktop's earlier socket startup problem was resolved after the user's Docker reset.
The next launch exposed a numeric environment-variable validation bug; angle/baud settings now
parse their environment strings before literal validation, with dedicated regression tests.

## Connecting the physical scanner

1. With scanner power off, verify the label is **LMS200-30106, 1015850** and identify the
   separate power/I/O and data connectors. An ordinary USB-C cable is insufficient.
2. Provide regulated 24 V DC ±15%, at least 2.5 A, with the correct power cable. Verify supply
   polarity and connector numbering using [HARDWARE.md](HARDWARE.md). Never put 24 V on data/USB.
3. Install the adapter's host driver. For RS-232, use genuine RS-232 levels and crossed TX/RX:
   scanner data 2 RxD → conventional PC 3 TxD, scanner 3 TxD → PC 2 RxD, ground 5 → 5.
   Leave scanner data pins 7–8 open. Verify the adapter's own pinout.
4. For four-wire RS-422 instead, cross by polarity: scanner 1 RD− → adapter TX−,
   2 RD+ → TX+, 3 TD+ → RX+, 4 TD− → RX−, and appropriate signal reference at pin 5.
   Bridge scanner data 7–8 only for RS-422. The old pins 3/4 diagram is incorrect.
5. Verify continuity, voltage standards, shielding, and connector orientation, connect data
   and the correct power cable, then apply external power. Allow up to 60 seconds for startup.
6. On Windows, install the native package, run `lms200 ports`, then
   `lms200 probe --transport serial --port COM3` using the actual port. Verify returned ID,
   status, and configuration. The probe is read-only.
7. For Docker, follow the exact token/bridge/Compose commands in [WINDOWS.md](WINDOWS.md).
   Initially choose `LMS_TARGET_BAUD=9600` in `.env`, run the native bridge, then
   `docker compose -f compose.yaml -f compose.bridge.yaml up --build -d`.
   Linux direct serial and macOS instructions are in [LINUX.md](LINUX.md) and [MACOS.md](MACOS.md).
8. Open the dashboard, confirm all hardware checklist items, and start. Verify angles and
   distances against known targets before relying on measurements. Move to 38400 only after
   basic communication works. Keep 500000 disabled until the adapter and line timing are qualified.
9. Stop through the dashboard or `docker compose stop`, wait for the confirmed `20/25` log,
   then stop the bridge and disconnect power as appropriate.

Remaining hardware verification includes actual firmware response profiles, real configuration
readback, electrical wiring/grounding, baud transitions, physical scan orientation/range accuracy,
USB buffering and timing, long-run loss rates, and stop confirmation with the real scanner.
The LMS200-30106 is not a certified machine-safety protective device.
