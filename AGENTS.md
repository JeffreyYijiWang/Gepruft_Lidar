# LMS200 project guide

Target: **SICK LMS200-30106, part 1015850**, legacy LMS2xx type 6. Not a certified
machine-safety protective device. External regulated 24 V DC ±15%, minimum 2.5 A.
USB-C alone is insufficient: host driver, USB RS-232 or four-wire RS-422 adapter,
correct power cable and data cable are required. Power/I/O and serial are separate
9-pin connectors. Never put 24 V on the data connector, USB, or adapter.

Corrected scanner data pins: 1 RD−, 2 RD+/RxD, 3 TD+/TxD, 4 TD−, 5 GND;
6/9 unused, 7–8 bridged ONLY for RS-422 (open for RS-232). Older manuals swap 3/4.
Cross TX to RX by polarity, not obsolete numeric wiring. See docs/HARDWARE.md.

Architecture: Python 3.12; pure protocol under `src/lms200/protocol/`;
CRC in `crc.py`, incremental framing in `framing.py`, typed commands separate from reads.
One asyncio device state machine owns serial/TCP/simulator/replay transports; API/CLI
share the service. Never import FastAPI, serial discovery, or Docker into protocol.
Keep real-device defaults read-only; require explicit hardware checklist before mutations.
Initialize through status → stop if necessary → read configuration → installation →
optional baud change/host change/status → variant → changed measurement config →
readback → monitoring-on-request → continuous. ACK AND matching response are required.
Stop uses 20/25; never blindly retry ambiguous configuration/baud writes.

Docker serial mapping is for Linux. Windows/macOS use native `lms200-bridge`;
Docker cannot install USB host drivers. Bridge data is transparent, control/auth/baud are
on a separate connection. 500 kbaud is explicit RS-422, host-paced, hardware-unqualified.
No privileged containers. Never reverse decisions in docs/adr/ silently; update ADR + this file.

Manuals (accessed 2026-09-06; full index and contradictions: docs/references/README.md):
* https://www.sick.com/media/pdf/3/43/843/dataSheet_LMS200-30106_1015850_es.pdf
* https://www.sick.com/media/docs/3/33/933/technical_information_lms200_211_221_291_laser_measurement_systems_en_im0027933.pdf — §1.1 p3 corrected data pinout.
* https://www.danarte.es/archivos/pdf/1866.pdf — pp4–12 power/wiring/setup; p12 up to 7 s configuration; p14 stop.
* https://sicktoolbox.sourceforge.net/docs/sick-lms-telegram-listing.pdf — §4 pp21–25 framing/timing; §7.4 pp40–45 modes/baud; §7.5 pp47–51 scans/origin; §7.6 pp52–57 status; §7.15 p65 model; §7.16 p66 variant; §7.43 p90 config read; §7.46 pp96–102 config write; §8 p106 status; §9 p107 CRC; §10.8 p124 overflow.

Commands: `python -m pip install -e '.[dev]'`; `ruff format --check .`; `ruff check .`;
`mypy`; `pytest -q`; `lms200 serve --transport simulator`; `docker compose up --build`.
Windows verification: `./scripts/verify.ps1`; POSIX: `sh scripts/verify.sh`.
Tests need no hardware; golden vectors must cite exact manual examples, synthetic fixtures
must say so. Include fragmented/noisy streams, NAK/timeouts, shutdown, bridge loopback,
replay and API/WebSocket integration. Hardware tests remain opt-in. Do not redistribute PDFs.
