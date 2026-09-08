# Linux

Install Python 3.12+, Docker Engine/Compose, and the USB serial adapter's host driver.
Identify the scanner device with `lms200 ports`; use a stable `/dev/serial/by-id/...` path
on the host when available. First follow [hardware wiring](HARDWARE.md).

## Direct serial mapping

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -c requirements.lock -e .
lms200 ports
lms200 probe --transport serial --port /dev/ttyUSB0
stat -c '%g' /dev/ttyUSB0
```

Give your host account appropriate serial-device group access (commonly `dialout`, depending
on distribution). Avoid world-writable device permissions. Set `LMS_SERIAL_DEVICE` and the
numeric `LMS_SERIAL_GID` from `stat` in `.env`; the image user is UID/GID 10001 and Compose
adds only the serial device's group. Group changes may require a new login.

```sh
docker compose -f compose.yaml -f compose.serial.yaml up --build -d
```

Open [localhost:8000](http://localhost:8000), probe, then complete the checklist before starting.
The container sees `/dev/ttyUSB0` regardless of the selected host path. No privileged mode
or Docker socket mount is used. The service begins read-only, with 38400 as the optional
target baud once you explicitly start. For RS-422 set `LMS_SERIAL_STANDARD=rs422` and check
the 7–8 bridge in the UI. Start at 9600 if you are commissioning an unknown adapter.

Device hotplug can invalidate an existing container device mapping. Stop acquisition and
recreate the container after checking the new host device. Do not run two serial owners.

## Host bridge alternative

```sh
export LMS_BRIDGE_TOKEN='your-locally-generated-token'
python tools/serial_bridge.py --port /dev/ttyUSB0 --baud 9600 --listen 0.0.0.0:7000
```

Put the same token in Compose `.env`. In another terminal:

```sh
docker compose -f compose.yaml -f compose.bridge.yaml up --build -d
```

This override includes `host.docker.internal:host-gateway`. Allow only the local container
environment through the firewall to TCP 7000/7001. The bridge remains native; the container
does not change host baud except via the explicit control connection.

## Tests and storage

```sh
python -m pip install -c requirements.lock -e '.[dev]'
sh scripts/verify.sh
docker build --target test -t gepruft-lms200:test .
```

The Linux test build opens a POSIX pseudo-terminal and runs real pyserial framing/initialization
against a synthetic scanner peer. It also tests the loopback serial bridge. No hardware is
required. macOS can run the PTY test as well, but was not directly exercised on this host.

Named recordings volume ownership is initialized by the image. For a bind mount, create
the directory beforehand and give UID 10001 write access according to your local policy.
Stop recording before exporting its `.bin`, `.metadata.json`, `.index.jsonl`, and `.jsonl` files.
