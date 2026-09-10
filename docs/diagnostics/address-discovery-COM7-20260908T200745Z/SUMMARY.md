# COM7 repeated status-address test — 2026-09-08

**The listener stayed open and recorded every byte Windows delivered. Windows
delivered zero bytes across all 685 requests. Repeated transmissions and changing
the request destination address did not resolve communication.**

This was one native Windows Python process, PID 24976, using one exclusive
Keyspan COM7 handle `0x2C4`. The current task's powered/green/startup-complete,
restored scanner cable/no loopback link/other COM7 applications closed
confirmations were retained. No physical change or additional loopback occurred.

| Phase | Destination | Attempts | Received bytes | Classification |
|---|---|---:|---:|---|
| Universal first | `00` | 50 | 0 | All SILENT |
| Individual addresses, only after universal silence | Every address `01` through `7F` | 5 each; 635 total | 0 | All SILENT |
| Entire run | `00` through `7F` | 685 | 0 | All addresses remained silent |

There were no responsive addresses, ACKs, NAKs, complete frames, partial frames,
or other received bytes. No complete `B1` was received; response-address matching
and response CRC are **not available**, not passed. Per-address counts, including
each of the 127 individual addresses, are in [result.json](result.json) and
[audit.json](audit.json). The request and recalculated CRC for every actual
attempt are retained in the result and timestamped log.

## Listener and raw-byte evidence

Windows UTC run interval: **20:08:37.055670–20:11:16.987976** (16:08–16:11 EDT).

- `listener_ready` at **20:08:37.077307 UTC**, after the worker completed its
  first read, before any request. The raw binary file was already open.
- The same read thread remained active through writes, drains, short waits and
  address changes for **159.881 seconds**. It completed **10,337 reads**.
- Fifteen ten-second heartbeats report increasing read counts, `serial_is_open:
  true`, and zero OS-delivered/saved bytes. There was no receive-thread error.
- Each nonempty read would first block subsequent TX, then write/flush the raw
  binary bytes and log their offset, count, hex, timestamps and attempt context,
  before exposing the data to parsing. The reader's simultaneous write/flush
  behavior was verified separately with synthetic bytes before this live run.
- [rx.bin](rx.bin) is **0 bytes**. It is empty because no bytes were delivered,
  not because STX searching or text decoding discarded them. OS byte count,
  saved byte count, raw file length and concatenated `rx_raw` records all agree.
- The reader stopped cleanly at **20:11:16.957945 UTC**. COM7 closed at
  **20:11:16.962945 UTC**. No listener, serial owner, or further run remains queued.

Initial pyserial open performs its own receive purge, as documented in the code
audit. After open there was no RX reset, purge, reopen, or alternate serial reader.
The explicit pre-TX listen lasted 200 ms; bytes arriving during that period would
have stopped transmission too.

## Configuration and transmission

**All 686 checked `GetCommState` calls passed**: one after configuration and
one before each of the 685 writes, all on handle `0x2C4`:

```text
BaudRate=9600; ByteSize=8
Parity=0=NOPARITY; StopBits=0=ONESTOPBIT (one stop bit)
fParity=0; fBinary=1
fOutxCtsFlow=0; fOutxDsrFlow=0; fDsrSensitivity=0
fDtrControl=0=DTR_CONTROL_DISABLE; fRtsControl=0=RTS_CONTROL_DISABLE
fOutX=0; fInX=0
```

Hardware and software flow control were disabled. Requested pyserial settings
are logged separately from the actual Windows DCB. The fresh pre-run enumeration
identified COM7 as `Keyspan USB Serial Port (COM7)`, hardware ID
`KEYSPAN\*USA19HMAP\00_00`.

Every request was exactly seven binary bytes in one `serial.write()` call, with
one corresponding pyserial `WriteFile`. All write returns were 7, all drains
completed with output queue zero, totaling **4,795 driver-accepted TX bytes**.

```text
First destination 00: 02 00 01 00 31 15 12  (CRC 1215; wire bytes 15 12)
Last destination  7F: 02 7F 01 00 31 E8 6D  (CRC 6DE8; wire bytes E8 6D)
```

The published `00` vector was checked before opening serial, and each individual
destination's CRC was recomputed. The offline audit independently rechecked every
transmitted packet's CRC and destination. Only command `31` was sent. No scanner
address-setting, baud, configuration, reset, start, or stop command was issued.

## Measured application timing

The application uses the Windows high-resolution performance counter. These are
host observations, not electrical timing measurements:

| Measurement | Actual value |
|---|---:|
| 50-attempt universal phase | 11.675 s |
| Interval between request write starts | 212.553–264.616 ms |
| Completed write call duration | 8.067–10.277 ms |
| Silent receive time after drain | 201.400–253.445 ms |

The requested target windows were 200–228 ms. Windows scheduling produced a
maximum observed 253.445 ms, slightly over 250 ms; no five-second per-attempt
delay was used. All intervals exceeded the required 100 ms minimum. The receive
worker continued independently through these waits.

There is no application byte-at-a-time loop or delay inside a telegram. The
adapter supplies normal UART start/stop framing. Seven bytes at nominal
9600/8-N-1 take about 7.29 ms in total, so an entire write call lasting more than
6 ms does not establish an inter-byte gap violation. A single buffered Windows
write removes deliberate application gaps, but cannot guarantee that the
Windows/USB/adapter path introduces no on-wire gap greater than 6 ms.

## Interpretation and next discriminating test

The repeated-destination strategy did not produce any exchange. The manufacturer's
universal-address rule and repeated retries make an address mismatch or one
occasionally missed command a less persuasive explanation of this run's silence.
This does not establish a specific physical fault or prove the scanner's baud.

The next discriminating check is the actual scanner serial signal path: verify
the cable's TX/RX crossover and signal ground, then observe the request at the
scanner's receive line and any output on its transmit line using suitable RS-232
measurement equipment. That can separate missing host-to-scanner delivery from
a missing or incompatible scanner response. Actual RS-232/RS-422 selection,
scanner baud, cable mapping and scanner interface behavior remain candidates.
The operator's passing bare-adapter loopback is retained; it does not verify the
complete scanner cable/path. No further physical action was performed or queued.

SICK [Telegram Listing](https://sicktoolbox.sourceforge.net/docs/sick-lms-telegram-listing.pdf)
section 4.3 p24 documents the timing/mirror-cycle retry considerations; sections
10.6–10.7 p124 identify universal `00`, individual `01..7F`, and factory address
`00`. Windows DCB/read/write/queue evidence confirms what the driver reports. It
does not prove scanner receipt or replace physical signal measurement.

## Implementation, checks and artifacts

- [Diagnostic source](../../../src/lms200/address_discovery.py) and
  [operating guide](../../ADDRESS_DISCOVERY.md).
- [Timestamped events/DCB/write/heartbeat log](events.jsonl), [raw RX](rx.bin),
  [complete result](result.json), [independent offline audit](audit.json), and
  [pre-run source hashes](source-manifest.json).
- Full offline suite: **233 passed, 2 skipped**. Final 20 discovery tests,
  Ruff format/lint, and mypy passed after the high-resolution clock change.
  Tests cover concurrent raw receipt during write and flush, pre-write DCB
  failure, any-byte stop, late universal response, all 685 scheduled attempts,
  response addresses through FF, bad CRC, fragmented/partial data, short writes,
  read failure and interruption. These synthetic tests are not scanner evidence.
- All ten saved source/dependency hashes still matched after execution.
  [The offline audit tool](../../../tools/verify_address_discovery.py) confirmed
  raw/log/count integrity, same-handle DCB checks, exact counts/CRCs, timing,
  listener progress and closure. It never opens serial.

The exact command already executed was:

```powershell
.\.venv\Scripts\python.exe -m lms200.address_discovery --run --confirm-powered-on-scanner-interface --output docs/diagnostics/address-discovery-COM7-20260908T200745Z
```

Exit code 1 represents no decoded matching B1, despite the completed diagnostic
and clean listener/handle closure. The preserved output directory is not reusable.
