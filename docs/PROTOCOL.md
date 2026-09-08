# LMS2xx protocol implementation

Primary source **TL**: SICK, *Telegram Listing LMS2xx*, 8007954/Q501, 2006-08-01,
[PDF](https://sicktoolbox.sourceforge.net/docs/sick-lms-telegram-listing.pdf).
**QM**: SICK, *Quick Manual for LMS communication setup*, v1.0, June 2001,
[PDF](https://www.danarte.es/archivos/pdf/1866.pdf). Page numbers below are printed pages,
which match one-based PDF pages. [Reference index](references/README.md) records corrections.

## Frame, CRC, and acknowledgement

All words are unsigned little endian. A host frame is:

```text
02 address length:u16 command:u8 parameters... crc:u16
```

Length counts command + parameters only. The response adds a final status byte inside the
length, immediately before CRC. CRC covers everything from STX through that status byte
(or final request parameter); it excludes the CRC itself. There is no ETX. STX/ACK/NAK values
can occur inside a payload without affecting framing. Sources: TL §4.2 pp21–24, Table 4-4.

Hexadecimal in the manuals/logs is a display of binary bytes. The diagnostic constructs
`bytes.fromhex("02 00 01 00 31 15 12")`, a seven-byte object, and passes it directly to
the serial write. It does not encode the printed digits or spaces as ASCII. QM p9's startup
example is 29 total bytes, payload length 23, CRC word `5A64` carried as `64 5A`; this is
a receive-side example, not a host command. Firmware text/status may change its checksum.

The CRC is not Modbus/IBM CRC-16. In `protocol/crc.py`: begin at zero; for each byte shift
the 16-bit result left **once**, conditionally XOR `0x8005` for the outgoing high bit,
then XOR `(previous_byte << 8) | current_byte`; retain 16 bits. Previous byte starts at zero.
No final XOR or bit reflection; append low byte first. TL §9 p107 defines this algorithm.

`Framer` incrementally buffers input, emits multiple frames per read, and ignores noise.
Impossible lengths and failed CRCs advance one byte and rescan. A stale incomplete candidate
can be expired by the caller to recover a valid frame behind it. TL p22 gives 812 bytes for
the largest ordinary frame; Table 7-25 p49 optionally adds two indices. The bound is therefore
814 total bytes, 808 payload bytes, for 401-point scans with indices. A synthetic regression
test exercises this combination; no large/unbounded allocation is accepted from length fields.

The scanner sends standalone ACK `06` or NAK `15`. A request completes only after ACK
**and** its expected CRC-checked reply. An ACK without a reply is a timeout. Unrelated
frames never complete a command. A `92` response is a logical command/state rejection,
distinct from standalone NAK (TL §7.3.4 p39). Unexpected addresses, commands, reserved
status severities, lengths, modes, units, and scan geometry are rejected or counted.

Address zero is the universal request address. TL examples reply at `80`; QM examples
reply at `81`. With broadcast requests, the decoder accepts only those two; with an
individual address 1–127 it requires `address | 80`. It never accepts arbitrary response
addresses. See TL §10.6 p124, §4.2 p24, QM p9.

## Implemented commands and responses

Layouts below are **payloads**, before framing. `S` is the final response status byte.
Every listed request receives ACK plus the listed response; malformed checksums may receive
NAK only, and semantically invalid requests may receive `92 S`. Those common rules apply
to every row. Timeouts and retry policy are in the following table.

| Name | Request payload | Reply payload and success rule | Required state | Exact source | Golden fixture |
| --- | --- | --- | --- | --- | --- |
| Request status | `31` | `B1 status_data S`; see status layout below | Monitoring/installation | TL §7.6, Tables 7-30–34 pp52–57; QM C.2 p9 | `status` |
| Request model/type | `3A` | `BA ASCII_device_ID S` | Monitoring/installation | TL §7.15, Tables 7-54–57 p65 | `type` |
| Read config part 1 | `74` | `F4 configuration S` | Monitoring/installation | TL §7.43, Tables 7-108–111 p90 | `read_config` |
| Enter installation | `20 00 password[8]` | `A0 00 S`; nonzero result is rejected | Stop output first; installation password | TL §7.4.1, Tables 7-11/12 pp40–41; §7.4.2 p45; QM C.6 p11 | `installation` |
| Baud 9600 | `20 42` | `A0 00 S`, then host baud change/readback | Output stopped; no password required | TL §7.4.1 Group D, Table 7-17 p44; QM C.4 p10 | `baud9600` |
| Baud 19200 | `20 41` | As above | As above | Same | `baud19200` |
| Baud 38400 | `20 40` | As above | As above | Same | `baud38400` |
| Baud 500000 | `20 48` | As above; explicit RS-422 mode | As above plus qualified RS-422 | TL Table 7-18 p44; QM D.2 p17 | `baud500000` |
| Set scan variant | `3B angle:u16 resolution_hundredths:u16` | `BB 01 angle:u16 resolution:u16 S`; result 1 and exact echo required | Output stopped; installation in this implementation | TL §7.16, Tables 7-58–61 p66; QM C.5 p11 | `variant180_1`, `variant180_half`, `variant100_quarter` |
| Write config part 1 | `77 configuration` | `F7 01 configuration S`; result 1 and full echo required | Installation | TL §7.46, Tables 7-121–124 pp96–102; timing QM C.6 p12 | Synthetic RMW vector below |
| Monitoring / stop | `20 25` | `A0 00 S` | May be sent during streaming or installation | TL Table 7-13 p41; QM C.9 p14 | `stop` |
| Start all complete scans | `20 24` | `A0 00 S`, then continuous `B0` frames | Configuration verified, output stopped | TL Table 7-13 p41; QM C.7 p12 | `start` |

Received unsolicited `90` (power-on) and `91` (software-reset acknowledgement) are recognized
and logged, with a fault if startup occurs while streaming (TL §7.3 pp38–39). No reset command
is implemented. No test/calibration/field/laser power commands are sent.

### Full golden telegrams

These expectations are copied from complete manual examples, not generated by the CRC under test.
`tests/fixtures/golden.json` is the machine-readable source for tests.

| Fixture | Complete telegram, hexadecimal |
| --- | --- |
| status | `02 00 01 00 31 15 12` |
| type | `02 00 01 00 3A 1E 12` |
| read_config | `02 00 01 00 74 50 12` |
| installation | `02 00 0A 00 20 00 53 49 43 4B 5F 4C 4D 53 BE C5` |
| baud9600 | `02 00 02 00 20 42 52 08` |
| baud19200 | `02 00 02 00 20 41 51 08` |
| baud38400 | `02 00 02 00 20 40 50 08` |
| baud500000 | `02 00 02 00 20 48 58 08` |
| variant180_1 | `02 00 05 00 3B B4 00 64 00 97 49` |
| variant180_half | `02 00 05 00 3B B4 00 32 00 3B 1F` |
| variant100_quarter | `02 00 05 00 3B 64 00 19 00 E7 72` |
| start | `02 00 02 00 20 24 34 08` |
| stop | `02 00 02 00 20 25 35 08` |
| mode_response_81 | `02 81 03 00 A0 00 10 36 1A` (QM p10) |
| mode_response_80 | `02 80 03 00 A0 00 10 16 0A` (TL Table 7-20 p45) |

The 77 test vector is **synthetic**, derived from TL Table 7-122. Start with the 34-byte
configuration built by `default_configuration()`; `.updated("cm", indices=True)` changes
only offsets 4 (set bit 1), 5 (mode 02), 6 (unit 00). `write_configuration()` frames `77`
plus those 34 bytes. The simulator expects ACK + `F7 01` + the same configuration + `10`.
The test verifies preservation of all other bytes and readback; the CRC's independent
golden checks are the official complete telegrams above. Simulator responses are synthetic,
never claimed to be hardware captures.

Full synthetic 77 vector for that cm/index-enabled configuration (computed CRC, not a golden
vendor checksum):

```text
02 00 23 00 77 00 00 46 00 02 02 00 00 00 02 02 02 00 00 0A 0A
50 64 00 0A 0A 50 64 00 0A 0A 50 64 00 00 00 00 02 00 9F 11
```

### Timing and retries

| Request class | ACK deadline | Response deadline after ACK | Attempts / retry policy |
| --- | --- | --- | --- |
| 31, 3A, 74 reads | 250 ms default | 3 s | At most 3; 30 ms between attempts |
| 20 mode / baud, 3B variant | 250 ms | 3 s | 1; no blind retry after ambiguous write |
| 77 configuration | 250 ms | 8 s | 1; accommodates QM's up-to-7-second change |

TL §4.3 p24 specifies ACK/NAK within 60 ms, at least 30 ms after NAK before retransmission,
up to 3 seconds for a mode change, up to 14 ms between scanner bytes, and 55 µs minimum /
6 ms maximum between host bytes. The 250 ms ACK deadline, 3 s read deadline, 8 s config
deadline, 250 ms stale-frame threshold, and default 4 s scan-idle timeout are **application
policies with host/USB scheduling margin**, not additional SICK specifications. Settings allow
bounded timeout adjustment. An ACK/response can arrive in the same read. Failed reads may
be repeated; successful configuration response and readback are both required.

## Initialization implemented

The native `lms200-hardware-diagnostic` entry point is the current commissioning tool:
`ports`, passive `listen-startup`, single-request `status`, and separately guarded adapter
`loopback`. See [Hardware diagnostic](HARDWARE_DIAGNOSTIC.md). It bypasses initialization,
preserves input, logs `write()` and `flush()` separately, and accepts no scanner mutation or
baud-change options. Status waits three seconds **after flush**, requiring a post-TX ACK and
valid B1. Passive startup accepts the documented 23-byte `90` payload at address 80 or 81,
with a 65-second bound after operator power-restoration confirmation (TL p38 <=60 s plus
host margin). It never transmits or performs a software reset.

The optional pure `Framer` observer exposes complete candidates, including failed CRCs, and
zero-based received-stream offsets for diagnostics. Normal consumers still receive only
CRC-valid frames and standalone controls. Raw noise/partial bytes remain in the diagnostic
journal even when the parser rescans them. The startup golden fixture in the diagnostic
tests is copied from QM p9, including wire checksum `64 5A`; it is not a hardware capture.

9600 is the documented delivery/startup default. TL Table 7-33 block B4 (p56) also describes
a permanent-baud option, so power-on at 9600 is not guaranteed for every previously configured
unit. No alternate baud is authorized in the current Keyspan diagnostic.

The separate native `probe-status` commissioning command bypasses initialization: exactly
one golden `31` request, fixed RS-232 9600 8-N-1, no retry/detection, no BA/F4, no stop command.
Its JSONL transcript records every received chunk, driver-accepted TX bytes, validated CRC,
and final result, including elapsed listening time. For diagnosis it waits up to 3 s even
without ACK, then allows 3 s after the first ACK to capture delayed USB/serial bytes. This
extended host timeout does not change scanner settings or the service's normal ACK policy.
It closes on success/failure/SIGINT and reports exact model as unavailable because BA was
not requested.

External startup is the operator's responsibility; optional `--startup-wait` delays opening.
There is no power/reset action. The state machine follows this sequence:

1. Open transport. Try 9600, 38400, 19200 in that order; add 500000 only with explicit
   RS-422 high-speed opt-in. At each candidate set the host adapter and send `31`.
2. Require ACK plus valid B1; verify reported baud agrees with the adapter. Request `3A`
   and `74`. Read-only probe ends here; closing a probe sends no stop/configuration command.
3. For authorized writes, require LMS200-30106 identity and no defective-device status.
   Send `20 25` to stop any pre-existing continuous output.
4. Compute requested geometry and read/modify/write configuration. If either differs, send
   `20 00` plus the eight-byte installation password (`SICK_LMS` by default).
5. If requested baud differs, send `20 42/41/40/48`. Receive complete A0 at the old rate,
   then change the **physical** adapter through serial or bridge control. Verify with `31`.
6. If geometry differs, send `3B` and verify BB's success and echoed angle/resolution.
7. If measurement settings differ, send `77` with the preserved config plus changed bytes.
   Wait up to 8 s for F7 success and exact echo. No repeated EPROM write for equal settings.
8. Read `74` and `31` again. Require geometry, unit, mode, and entire config to match.
9. Send `20 25` to return to monitoring-on-request. `configure` ends here.
10. Send `20 24`, require ACK + A0, then decode B0 continuously.
11. Shutdown/cancellation/error cleanup attempts `20 25`, requires ACK + A0 when available,
    logs whether stop was confirmed, cancels the reader and closes the transport.

Default broadcast A0 cannot identify which 20 subcommand it acknowledges. Consequently
the application serializes all commands and avoids retries of uncertain mutations.
If communication fails across a baud change, host/scanner rates may differ. Do not guess
the result; reconnect with controlled detection. The bridge never interprets scanner bytes.

## Status data layout and documented discrepancy

For B1, `data[0]` below means the first byte **after B1**, excluding final status:

| Field / TL Table 7-33 block | 146-byte table layout | 152-byte wire layout |
| --- | --- | --- |
| Firmware A | 0..6, ASCII | Same |
| Operating mode B | 7 | Same |
| Defective-device status C | 8; nonzero means error/fatal | Same |
| Reserved D | 9..10 (table says WORD) | 9..16 |
| Measuring mode A2 | 95 | 101 |
| Scan angle A5 | u16 at 100 | u16 at 106 |
| Resolution A6 | u16 at 102, 1/100° | u16 at 108 |
| Active baud B2 | u16 at 109 | u16 at 115 |
| Permanent-baud flag B4 | 112 | 118 |
| Scanner address B5 | 113 | 119 |
| Unit B7 | 115 | 121 |

TL Table 7-33 pp52–57 adds to 146 bytes if reserved D is one WORD, but Table 7-34's
complete frame declares 152 status-data bytes. The maintained
[SICK Toolbox source](https://github.com/ros-drivers/sicktoolbox/blob/master/c%2B%2B/drivers/lms2xx/sicklms2xx/SickLMS2xx.cc),
function `_getSickStatus`, uses payload offsets 107/109/116/122 for angle/resolution/baud/unit,
where its payload includes B1. These correspond to data offsets 106/108/115/121 above,
and substantiate the six-byte reserved-block discrepancy. Both exact lengths are supported;
all others fail closed. Field meanings are from the manual; the reserved-byte contents are
not interpreted. This correction is explicitly corroborated by implementation evidence,
not presented as an unambiguous manual layout. Real firmware still needs verification.

Baud words (TL p56): `8067`=9600, `8033`=19200, `8019`=38400, `8001`=500000.
The ASCII identity returned by BA is retained rather than converted into an assumed product label.
Laser-switch meaning at B8 is not decoded because p57 repeats `00` for both states.

## Configuration offsets

The configuration excludes F4/F7/77, acceptance result, and final status. TL Table 7-122:

| Offset | Size | Block / meaning | Application action |
| --- | --- | --- | --- |
| 0 | 2 | A, blanking | Preserve |
| 2 | 2 | B, stop/peak threshold | Preserve |
| 4 | 1 | C, availability / real-time indices | Change bit 1 only |
| 5 | 1 | D, measuring mode | Set 02: 13-bit distance and field A/B/C |
| 6 | 1 | E, length unit | 00 cm or 01 mm |
| 7..31 | 25 | F through A3, field/restart/contour parameters | Preserve byte for byte |
| 32..33 | 2 | A4, dazzle evaluation count (later extension) | Preserve when present |

QM uses a 32-byte earlier configuration; TL p102 shows 34 bytes. Only those two lengths
are accepted. The extension is preserved and not manufactured for an older device. TL p90's
wording says 33 bytes but its length field requires 34; field widths and p102 are used.
QM's canned 77 mode `0D` is **not used**: TL p98 marks it reserved. This project deliberately
selects documented mode 02 and preserves the scanner's thresholds/field settings.

## Measurement B0 and coordinates

B0 data starts with a u16 header: count in bits 0–9, bit 10 reserved, bits 11–12 raster,
bit 13 partial scan, bits 14–15 unit (`00` cm, `01` mm; `1x` reserved). The service only
accepts complete standard scans with bits 10–13 zero. Count must equal `angle/resolution+1`.
Next come count u16 distance words, optional scan and telegram index bytes (when configured),
then the response status. The expected length is exact.

Each 13-bit distance value is `raw_word & 1FFF`. The upper bits in mode 00 are field A,
field B, dazzle; in mode 01 they encode reflector level 0–7; in mode 02 they are field A/B/C.
TL §7.46 p98 determines meaning; the same bit is not universally an error flag.

TL §10.8 p124 special values: `1FFF` invalid/no stop, `1FFE` dazzling, `1FFD` arithmetic
overflow, `1FFB` low signal-to-noise, `1FFA` channel 1 read error, `1FF7` above maximum.
Other values at or above `1FF7` are marked reserved special values. Invalid distances and
mode-00 dazzling have null coordinates, never misleading ordinary points. Raw words and
flags remain available in exports and recordings.

TL §7.5.2 p48 and Figures 7-1/7-2 establish the top-view direction: 0° right, 90° forward,
180° left, increasing counterclockwise. The 100° variant is physically **40° through 140°**.
The application uses `starting_angle=(180-angle)/2`, positive resolution as the increment,
and `x=distance_m*cos(angle)`, `y=distance_m*sin(angle)`. Scanner-local 0..100 labels are not
mistaken for physical 0..100 degrees.

TL p19 gives mirror 75 Hz and 1, 2, or 4 rotations per complete 1°, 0.5°, 0.25° scan.
Serial 8-N-1 needs 10 bits per byte. With count N and real-time indices, the line ceiling
is `baud / (10 * (2*N+12))` complete scans/s, before other overhead. Displayed receive Hz
is measured from actual scan arrivals, separately from nominal mirror and complete-scan rates.

Final status byte (TL §8 p106): bits 0–2 encode 0 OK, 1 info, 2 warning, 3 error, 4 fatal;
5–7 are reserved severity values and rejected. Bits 3–4 identify data source, bit 5 restart,
bit 6 implausible measurements, bit 7 pollution. Warning flags are preserved; error/fatal
measurement frames fault streaming. A read-only B1 may still report device faults for diagnosis.
