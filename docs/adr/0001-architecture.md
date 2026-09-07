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

Update this ADR and AGENTS.md together when changing these decisions.
