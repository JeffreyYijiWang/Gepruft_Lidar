# Windows

Install Python 3.12+ and the USB serial adapter's Windows driver. Confirm its COM port in
Device Manager or `lms200 ports`. Docker cannot install this host driver. A USB-C cable
alone is insufficient; follow [hardware wiring](HARDWARE.md) first.

## Native host bridge + Docker Desktop

For the initial **single status telegram** test, use the native host command after Windows
assigns the verified Keyspan COM port and wiring/startup are confirmed:

```powershell
.\.venv\Scripts\lms200.exe probe-status --port COMx --log status-probe.jsonl
```

Replace COMx with the actual Keyspan port. This command fixes RS-232 to 9600 8-N-1, clears
stale input, sends only `02 00 01 00 31 15 12`, logs TX/RX and CRC results, and closes.
It accepts no baud/configuration options and reads no environment settings. The ordinary
`probe` below additionally queries model/configuration and can search baud. Do not use it
when authorization is limited to a single status request. Current physical results are in
[the hardware diagnostic log](HARDWARE_DIAGNOSTIC_LOG.md).

In PowerShell in the repository:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -c requirements.lock -e .
.\.venv\Scripts\lms200.exe ports
.\.venv\Scripts\lms200.exe probe --transport serial --port COM3
```

Probe waits for ACK and status without scanner configuration writes. If the device has
just received external power, allow startup to finish or add `--startup-wait 60`.
Do not run a native probe at the same time as the bridge owns the port.

Generate a local token, put the same value into `.env` as `LMS_BRIDGE_TOKEN`, and export
it in the bridge's terminal. The token is a local access control, not encryption.

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
# Set the value privately in your terminal and .env:
$env:LMS_BRIDGE_TOKEN = 'replace-with-your-generated-token'
.\.venv\Scripts\python.exe tools/serial_bridge.py --port COM3 --baud 9600 --listen 0.0.0.0:7000
```

Leave that terminal running. Permit TCP 7000/7001 only from the local Docker environment
using the Windows host firewall. Do not expose these ports on untrusted/public networks.
The default control port is 7001; 7000 opens only while a lease exists.

In another terminal:

```powershell
docker compose -f compose.yaml -f compose.bridge.yaml up --build -d
```

Open [localhost:8000](http://localhost:8000). **Probe status** reads information; **Start scan**
requires the hardware checklist. The default bridge Compose target is 38400 baud: scanner
acknowledges at the old rate, bridge changes COM3 through control, then scanner status
confirms the new rate. `.env` may select `LMS_TARGET_BAUD=9600` for first commissioning.

For a native TCP probe against the already running bridge:

```powershell
$env:LMS_TOKEN = $env:LMS_BRIDGE_TOKEN
.\.venv\Scripts\lms200.exe probe --transport tcp --host 127.0.0.1 --port 7000 --control-port 7001
```

Only one client can hold a bridge lease. Stop the container first before using a separate
native probe. Stop streaming/container before quitting the bridge:

```powershell
docker compose -f compose.yaml -f compose.bridge.yaml stop
# Then Ctrl+C in the native bridge terminal.
```

## Native application option

```powershell
.\.venv\Scripts\lms200.exe serve --transport serial --port COM3 --target-baud 38400
```

The dashboard starts read-only. Use its checklist before starting the physical scanner.
This avoids the bridge and Docker entirely while retaining the same protocol/application.

## High speed and Docker startup

RS-422 500000 baud requires a qualified adapter, corrected wiring, scanner pins 7–8 bridged,
bridge `--high-speed`, and service `LMS_HIGH_SPEED=true`, `LMS_SERIAL_STANDARD=rs422`,
`LMS_TARGET_BAUD=500000`. Use the native CLI options or explicitly add those environment
keys to a local Compose override. Actual Windows scheduling/USB timing is not guaranteed.

If Docker Desktop cannot start because `Docker\run\sailor-ingest.sock` is inaccessible,
the application cannot repair the Windows kernel's socket state. Save work and restart
Docker/Windows as appropriate, then wait for `docker info` to succeed and rerun Compose.
Do not delete data directories or reset volumes as a routine application troubleshooting step.
This project's initial build was blocked by that host problem; it succeeded after the user
reset Docker and the environment-variable parsing regression was fixed.
