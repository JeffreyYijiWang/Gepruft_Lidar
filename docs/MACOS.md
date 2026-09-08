# macOS

Install Python 3.12+ and the adapter's macOS host driver. Some adapters need a vendor driver
and macOS approval; others use a built-in driver. Follow its vendor instructions. Docker
does not install that driver. Use the host call-out path, typically `/dev/cu.usbserial-XXXX`
or `/dev/cu.usbmodem...`, after checking `lms200 ports`. Read [hardware wiring](HARDWARE.md).

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -c requirements.lock -e .
lms200 ports
lms200 probe --transport serial --port /dev/cu.usbserial-XXXX
```

Probe is read-only and tries documented rates through the host adapter. Connect external
24 V power first and wait for scanner startup; USB-C alone cannot connect or power it.

## Docker Desktop host bridge

Generate a token with `python -c "import secrets; print(secrets.token_urlsafe(32))"`, keep the
same value in Compose `.env` and the native terminal, then run:

```sh
export LMS_BRIDGE_TOKEN='your-locally-generated-token'
python3 tools/serial_bridge.py --port /dev/cu.usbserial-XXXX \
  --baud 9600 --listen 0.0.0.0:7000
```

In another terminal:

```sh
docker compose -f compose.yaml -f compose.bridge.yaml up --build -d
```

Open [localhost:8000](http://localhost:8000). Probe, verify ID/status, then complete the
hardware checklist to enable streaming/configuration. The container reaches the native
bridge through `host.docker.internal`; control port 7001 coordinates adapter baud changes.
Allow only the local Docker environment to reach ports 7000/7001. Do not bind the bridge
publicly without appropriate local firewall restrictions or an encrypted tunnel.

Stop the container first, verify the LMS `20/25` stop confirmation, then Ctrl+C the bridge.
Direct host USB serial mapping to Linux Docker Desktop containers is not the supported path.

The native application can also run directly with:

```sh
lms200 serve --transport serial --port /dev/cu.usbserial-XXXX --target-baud 38400
```

The implementation uses portable pyserial/asyncio APIs. Native macOS drivers, Apple Silicon
container builds, real RS-422 custom-rate support, and USB timing were not verified on the
Windows development host. 500000 remains explicit opt-in and needs actual adapter validation.
