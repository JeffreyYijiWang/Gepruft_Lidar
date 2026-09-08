# Troubleshooting

## Current Windows/Keyspan commissioning

Use [Native hardware diagnostic](HARDWARE_DIAGNOSTIC.md) for this physical LMS200-30106.
The Keyspan USA-19HS is COM7, RS-232 only. Both signed KSPN drivers now report OK/error 0.
The scanner's green LED and slow Keyspan flashing are operator observations. Previous native
status writes returned seven bytes, but RX stayed empty for three seconds; no ACK or response
CRC was available, and the old tool never called `flush()`. Physical TX remains unverified.

Latest staged test at 22:14 EDT: the operator power-cycled with the passive listener already
open. RX was `10 04 21 00 28 01 A0`, no valid `90` frame/CRC. The following single status
request returned seven from `write()`, completed `flush()` with output queue zero, and received
zero bytes in 3.031 s. No ACK/NAK; both ports closed. Bytes during power-up do not establish a
valid scanner telegram. The next isolation step requires physical disconnection and explicit
confirmation before the adapter-only loopback; it has not been performed.

At the user's request, repeated the test at 22:18-22:22 EDT with separate OFF/LEDs-off and
ON confirmations. Listener was open before both steps and did not clear RX. It captured
`00 39 14 31 21 31 01`, without a valid startup frame. The following status request again
returned seven from write and completed flush; RX remained empty for 3.015 s. Both handles
closed. Code inspection confirms binary `bytes.fromhex`, not transmission of ASCII hex digits;
both the request and manual startup example CRC pass offline. Continue physical isolation only
after the required operator confirmations; timing/hex-format concerns alone do not explain
this repeat's missing valid response.

Use `lms200-hardware-diagnostic ports`, then `listen-startup --port COM7`, followed by one
`status --port COM7` only after the passive test. Startup capture requires the operator to
power-cycle the normal scanner supply after the listener is ready. Never clear the receive
buffer during startup. Default 9600 after power-on is qualified by the later telegram manual's
permanent-baud option; this phase still permits only 9600. No automatic baud search is allowed.

If still silent, prepare the isolated Keyspan 2-3 loopback, but do not run it or request jumper
work until the operator confirms scanner power off, scanner cable disconnected and USB-only
adapter connection. Cable crossover is not yet verified. All physical inspection/continuity
work requires power off and disconnection. Serial Assistant and bridge must not share COM7.
Stop when further progress needs a physical action and obtain the user's confirmation.

The general commands below describe the broader application, not authorization to use its
configuration or baud-detection paths during this restricted diagnostic phase.

| Symptom | Check / action |
| --- | --- |
| USB-C cable connected, no scanner | LMS200 requires external 24 V and an RS-232/RS-422 adapter; it is not a USB scanner |
| Red + yellow LEDs | Wait for startup; TL allows up to 60 s. Verify supply and cable voltage drop |
| Red LED alone | May be a monitored-field infringement; read status rather than assuming serial failure |
| No port found | Install/check host adapter driver; run native `lms200 ports`, not container port enumeration |
| Multiple ports found | Supply `--port`; automatic selection only accepts exactly one enumerated serial port |
| Access denied/busy | Stop other serial owners. Linux: check numeric device group; Windows: COM name; macOS: call-out tty |
| Probe timeouts at all rates | Check supply, startup, correct data connector, voltage standard, jumper, crossover and polarity |
| Constant NAK | Check framing/CRC, serial format, noise, adapter timing. NAK is not a successful reply |
| ACK but no complete reply | Configuration may take 7 seconds; increase bounded timeout margin if bridge scheduling is poor. Do not blindly repeat writes |
| CRC or truncated-frame errors | Check cable/shield/ground, USB driver, adapter buffers, baud accuracy and workload |
| Unsupported status/config layout | Preserve raw B1/config data and firmware ID. The manuals conflict; add a tested explicit profile rather than guessing offsets |
| F7 rejected | The newer manual requires result 01; the older quick example differs. Preserve a capture and verify firmware semantics before changing acceptance |
| Low scan Hz | Compare actual received rate, nominal complete-scan rate, and serial ceiling. 9600 baud cannot transmit 75 full scans/s |
| Missing/invalid points | Inspect per-point raw flags and special codes; mm mode represents about 8 m, cm about 80 m. Dark-target range can be about 10 m |
| Permission to start denied | Complete hardware consent and explicitly enable writes. Read-only probe is always the first operation |
| Bridge connection refused | Native bridge running? Reachable host bind address? Token set? Control 7001 open? Data 7000 is opened only after a lease |
| Bridge lease rejected | Token mismatch or another active client. Stop previous client and reconnect; no parallel controllers |
| Switching host baud did nothing | The scanner must receive its documented baud command first. Use the controlled bridge; a plain socket cannot configure a physical adapter |
| Stop unconfirmed | The transport may have failed or baud may differ. Check communication and re-probe; don't assume output stopped |
| Recording won't start | Stream must be active and recording volume writable by UID 10001. Check free space and queue-drop counters |
| Replay lacks geometry | Keep the `.metadata.json` beside the raw `.bin`; raw B0 does not carry angle/resolution itself |
| Replay completed | Use Reconnect to reopen and replay from the beginning |
| Docker health is 503 | Inspect `/api/status` and container logs; faulted hardware state is different from a crashed web process |
| Docker engine inaccessible | Resolve host Docker Desktop startup first. No application container can repair a stopped engine |

Useful commands:

```sh
lms200 diagnose --transport serial --port /dev/ttyUSB0
docker compose ps
docker compose logs --tail 100
```

For a control bridge probe, stop the container owner first, set `LMS_TOKEN` equal to the
native bridge token, then use `lms200 probe --transport tcp --host 127.0.0.1 --port 7000
--control-port 7001`. For a third-party bridge without control, configure its baud natively
and use `--fixed-baud --baud RATE`; omit `--target-baud`.

Normal service diagnostic logs omit raw command payloads, installation passwords, and bridge
tokens. The separate native hardware diagnostic deliberately preserves all permitted TX/RX
hexadecimal bytes in an append-only journal. Read-only exported status includes raw B1 and
configuration for protocol diagnosis.
The synthetic simulator ID is identified as simulation by the transport field; it is not
evidence that a physical scanner was detected.

Physical acceptance should cover startup/status, every requested geometry/unit, readback,
mode transition timing, correct cable polarity, sustained acquisition, recovery after cable
disconnect, and confirmed graceful stop. Validate 500-kbaud line timing with qualified
equipment; software loopback is not an electrical timing test.
