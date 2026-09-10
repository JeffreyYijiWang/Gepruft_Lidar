# Windows status-address discovery

The opt-in `python -m lms200.address_discovery` diagnostic implements the user's
repeated-address test and keeps a dedicated receive worker running through the
entire test. It opens Keyspan COM7 once, natively on Windows, at 9600/8-N-1 with
hardware/software flow control off and DTR/RTS disabled. No ROS, bridge, or other
serial owner runs alongside it. Existing single-status defaults are unchanged.

The current operator confirmations in this task cover powered/green/completed
startup, the scanner data cable restored, adapter loopback link removed, and
other COM7 programs closed. The user's new request explicitly authorizes the
bounded repeated destination-address test on that setup. Changing the request's
destination byte does not configure or store a scanner address. No address-setting,
baud-changing, scan, stop, configuration, or reset telegram is sent.

## Reader and evidence

- Before any serial open, validate the published universal status CRC: input
  `02 00 01 00 31`, numeric CRC `1215`, transmitted bytes `15 12`.
- Create a new output directory, `events.jsonl` and `rx.bin`; existing directories
  are refused. Open one exclusive pyserial Windows handle. Check its actual DCB
  after configuration and again before every write using `GetCommState` on that
  same handle. Requested properties and actual Windows fields are logged separately.
- Start one receive thread and require it to complete a read before signaling
  `listener_ready`. A 200 ms pre-TX listen follows. The reader stays active during
  each write, flush, short attempt window, address transition, and response capture.
  Ten-second heartbeats report completed read calls, open-port state and byte counts.
- On every nonempty read, immediately block future sends, write/flush the original
  bytes to `rx.bin`, and log timestamp, raw offset/count/hex and current attempt
  context. Only then expose the bytes to the parser. Bytes preceding STX, ACK/NAK,
  noise, and incomplete telegrams all remain in the raw file.
- A completed binary read is required before first TX. A failed/stalled receive
  worker, failed DCB check, partial write or unsuccessful drain aborts further TX.
  `flush()` waits for outgoing data; no application RX purge/reset/reopen occurs.
  Installed Windows pyserial itself purges during its initial `open()`; this tool
  cannot preserve bytes discarded before its listener starts.
- At completion or interruption, stop/join the receive thread and close COM7.
  Save `result.json`, including all 128 address attempt counts, per-attempt writes,
  classifications and timing, raw-file length/SHA256, and OS/saved byte counts.
  Zero bytes are reported as zero, not as a successful scanner exchange. The
  listener stays open for the test's duration and closes when the bounded test ends.

## Schedule and parsing

Phase 1 sends address `00` at most 50 times. Each seven-byte packet is one binary
`serial.write()` operation. After drain, use alternating 200, 207, 214, 221 and
228 ms receive windows; every transmission is separated by at least 100 ms.
The varying intervals avoid deliberately locking retries to one fixed period.
Fifty silent attempts should take roughly 11–13 seconds including Windows I/O.

Phase 2 is reachable only after all 50 universal requests are silent. It tries
`01` through `7F`, five times each, with the same windows and a newly calculated
SICK CRC for every destination. The absolute maximum is 685 requests / 4795
driver-accepted bytes, with a 240-second overall discovery deadline. A normal
fully silent run should take about 2.5–3 minutes.

**Any received byte ends all further transmission**, including during the
pre-TX listen, DCB readback, a write, or an address transition. A write already
submitted to Windows cannot be retroactively withdrawn; receive checks immediately
before each whole-buffer write prevent subsequent attempts once bytes are observed.
There is no new request while a response is being processed and no retry after NAK.
Thus the manual's minimum 30 ms NAK-to-retransmit rule is not exercised.

After the first byte, continue recording. An ACK without a telegram allows up
to one second for a response to start. An incomplete telegram or other received
data gets a 250 ms idle allowance after the most recently delivered byte,
including the documented 14 ms scanner gap and Windows/USB scheduling margin.
An overall 15-second response-capture limit bounds continuously arriving data.
No five-second wait is applied to silent attempts. Partial bytes are retained
when the capture ends, and the reader remains active through cleanup.

Parsing uses little-endian payload length to determine the full size
(`payload length + 6`) and verifies CRC before claiming a complete frame.
All response addresses through `FF` are retained. It reports `ACK`, `NAK`,
`RESPONSE`, `PARTIAL`, `OTHER`, or `SILENT`, with a list when several apply.
Control bytes inside a complete telegram are payload, not standalone ACK/NAK.
Bad-CRC candidate payloads are not rescanned for misleading control bytes.
Malformed data remains available in raw evidence even if decoding cannot recover it.

For every complete frame, report whether the command is `B1` and whether the
response address equals exactly `request + 80h`. In particular, an address-`81`
reply to a universal request is recorded as a strict mismatch, preserved for
review, and stops the scan; it is never discarded merely because it differs
from `80`. Other project manuals contain broadcast examples with `81`.
Without transaction IDs, association with the most recent request is temporal
evidence, not proof that a late byte belongs to that particular retry.

## Timing and source limits

The application's write and drain call durations and request spacing are logged.
There is no per-byte loop, sleep, string conversion, manual start/stop bit, or
extra write inside a request. The seven binary bytes are passed together to
pyserial's single Windows `WriteFile`. At nominal 9600/8-N-1, seven bytes occupy
about 7.29 ms of serial framing; total write duration above 6 ms is not itself an
inter-byte gap above 6 ms. The code adds no application delay between request
bytes, but Windows/USB/adapter behavior may still affect the physical signal.
Application timestamps and driver queue counts cannot prove the precise wire
gaps; that requires a separate logic-analyzer or oscilloscope test.

Manufacturer source checked 2026-09-08: SICK
[LMS2xx Telegram Listing](https://sicktoolbox.sourceforge.net/docs/sick-lms-telegram-listing.pdf),
section 4.3 p24 (6 ms host gap, up to 14 ms scanner gap, ACK/NAK timing, mirror-cycle
misses and possible repeats), section 9 p107 (CRC polynomial/algorithm), and
sections 10.6–10.7 p124 (universal `00`, individuals `01..7F`, factory address `00`).
These specifications support a repeated test; they do not establish why this
particular scanner has been silent. Likewise, DCB readback confirms what the
driver reports and is not a signal measurement or proof of scanner receipt.

## Commands

From repository-root native Windows PowerShell, offline review first:

```powershell
.\.venv\Scripts\python.exe -m lms200.address_discovery
.\.venv\Scripts\python.exe -m pytest -q tests/test_address_discovery.py
```

After current setup confirmation, a separately authorized run uses a **new**
output directory and sole COM7 ownership:

```powershell
.\.venv\Scripts\python.exe -m lms200.address_discovery --run --confirm-powered-on-scanner-interface --output docs/diagnostics/address-discovery-COM7-NEW
```

Use native Windows execution outside the restricted agent sandbox, as with the
previous DCB verification. Do not disable Windows security or reinstall drivers.
Ctrl+C ends the test and preserves its partial evidence. Exit 0 requires a decoded
matching B1 and clean capture/close; exit 1 can be a completed fully silent test.

The [2026-09-08 completed live run](diagnostics/address-discovery-COM7-20260908T200745Z/SUMMARY.md)
kept one listener active for 159.881 s / 10,337 reads. All 50 universal and 635
individual requests were silent; OS, saved-file and log byte counts were all zero.
All 686 DCB checks and 685 seven-byte writes passed. The listener and COM7 are
closed; no run is queued.
