# Native LMS200 hardware diagnostic

Target: SICK LMS200-30106, part 1015850, on Windows through Keyspan USA-19HS **RS-232**.
Use fixed **9600 baud, 8 data bits, no parity, one stop bit**, all flow control disabled.
Only passive startup capture and one `31` status request per authorized attempt are allowed.
Loopback is a separate adapter-only test requiring explicit physical isolation confirmation.
No Docker bridge, Serial Assistant test, or other serial application may run concurrently.

## Verified observations and remaining questions

| Item | Evidence / result |
| --- | --- |
| Scanner power and startup | Operator confirmed separate 24 V supply and completed startup |
| Scanner LED | Operator reports green |
| Keyspan LED | Operator reports slow flashing; no sustained activity observed |
| Windows port | `Keyspan USB Serial Port (COM7)` |
| Port PNP ID | `KEYSPAN\*USA19HMAP\00_00` |
| USB parent PNP ID | `USB\VID_06CD&PID_0121\6&2C1F58E1&0&1` |
| USB identifiers | VID `06CD`, PID `0121`; virtual COM child has no direct VID/PID fields |
| Driver provider | `KSPN` |
| Port driver | `17.14.44.551`, `oem79.inf`, service `USA19HP` |
| USB driver | `17.14.44.557`, `oem74.inf`, service `USA19H` |
| Signing | Both Microsoft Windows Hardware Compatibility Publisher; `IsSigned=true` |
| Native device status, 2026-09-07 02:01 UTC | Both `OK`, ConfigManagerErrorCode `0` |
| Driver release date | 2024-08-16 (CIM displays midnight UTC as previous evening EDT) |
| Possible serial applications | No matching Keyspan/LMS200 process at inventory time; this alone cannot prove ownership |
| Availability | Previous exclusive COM7 opens succeeded; availability must be checked on each open |
| Latest physical status attempt | 2026-09-06 22:22 EDT: COM7 opened/closed; exactly one write returned 7, flush completed/output queue 0; RX 0 after 3.015 s |
| TX bytes accepted by Windows | `02 00 01 00 31 15 12` |
| Request CRC | Expected/encoded `1215`, wire `15 12` |
| Physically transmitted on DB9 | Not established by `write()` alone; no electrical capture or loopback yet |
| Output flush | Completed in the new 22:14 and 22:22 status tests; not called in the older probes |
| Status RX / ACK / NAK / response CRC | RX empty; neither control byte; no response CRC available |
| Latest passive startup capture | Separate off/LEDs-off and on confirmations; listener open throughout. RX `00 39 14 31 21 31 01`; no valid startup frame within 65 s of power-on confirmation |
| Native adapter loopback | Prepared, not performed. Operator confirms LMS200 off, black Q.C. adapter and gray scanner cable removed, USB-only Keyspan with DB9 exposed. Pin 2-3 jumper confirmation still pending |
| Cable TX/RX crossover | Not verified by continuity or a successful exchange |
| Scanner data pins 7/8 | Operator previously confirmed open; no physical inspection by software |

The driver-installation blocker is resolved. The serial path is not yet isolated to
the adapter, cable, or scanner interface. The passive bytes establish that Windows delivered
some input; without STX/framing/CRC they cannot identify its origin or verify an LMS200 path.
Green/idle LEDs and a successful host write/flush do not identify a failed scanner.
A retained nondefault scanner baud is another unresolved possibility;
the current authorization still permits **9600 only**. No change to Windows security is needed.

The remaining fault is most plausibly in the serial signal path or its settings, rather than
missing driver installation or failure to call `write()`. Adapter faults, noise, grounding,
crossover, interface selection and retained baud cannot yet be distinguished. **Stop condition
5 applies:** further isolation requires physical disconnection and explicit loopback preparation
confirmation. No loopback, cable opening, continuity check or additional status retry was done.

Latest raw [append-only journal](diagnostics/hardware-raw.jsonl): startup run
`8bc94614-04ef-46bd-8e68-c76c69dfe9bb`, status run `9f9fa19d-f2f7-45b4-beac-7af8e0b7eda4`.
Both COM7 handles are closed. No process from these tests retains serial ownership.

## Audit of the previous `probe-status` implementation

| Requested check | Finding in `src/lms200/status_probe.py` and physical JSONL |
| --- | --- |
| Native or Docker | Native Windows Python, direct pyserial COM7 |
| Serial format | 9600, 8-N-1; read timeout 20 ms, write timeout 250 ms |
| Hardware flow control | `rtscts=False`, `dsrdtr=False` |
| Software flow control | `xonxoff=False` |
| DTR / RTS | Both false before opening; driver-level opening transitions were not electrically measured |
| `write()` | Called once with the documented seven bytes; returned 7 |
| `flush()` | Not called; earlier reports cannot establish output flushing |
| Listening order | After write; the three-second timer started after `write()` returned |
| Input clearing | Called `reset_input_buffer()` after open; queued startup data could be discarded, but there is no evidence it was present |
| Standalone ACK / NAK | Framer preserves both outside telegrams; NAK ends the attempt |
| Fragmented replies | Incremental buffer preserved across reads; final partial bytes logged |
| CRC failures | Counted and raw RX saved; older log did not expose every failed candidate CRC |
| Other port owner | Exclusive open succeeded on each recorded attempt; no simultaneous owner then |
| Closure | `finally` closed the handle; no cleanup/stop telegram |

The missing flush is an evidence gap, not proof that no bytes reached the adapter. Installed
pyserial's Windows `write()` waits for the overlapped write result at a positive write timeout.
Its `flush()` waits for the driver's output queue to drain. Neither is an oscilloscope capture.
Windows pyserial also purges buffers during **open**: arm startup capture before power-on.
DTR/RTS are not needed on a correctly wired three-signal RS-232 link; if the cable routes
control lines unexpectedly, software cannot rule out their effect. No control lines are toggled
as an experiment.

## Commands

### Binary bytes and hexadecimal display

`STATUS_REQUEST = bytes.fromhex("02 00 01 00 31 15 12")` creates **seven binary bytes**.
Their decimal values are `[2, 0, 1, 0, 49, 21, 18]`; the serial write receives that `bytes`
object. Spaces and printed hex digits are display formatting, not extra transmitted characters.
RX is also raw binary, displayed by `.hex(" ").upper()` without ASCII decoding of the stream.

The Quick Manual p9 startup example is **29 bytes** including the four-byte header, 23-byte
payload and two-byte CRC. Its computed CRC is `5A64`, carried low byte first as `64 5A`.
That startup telegram comes **from the scanner** and is never sent by our passive listener.
The live firmware text/status/CRC may differ from the manual's example. The verified request
CRC remains `1215`, carried as `15 12`. These checks are offline and transmit nothing.

The operator questioned the first power-cycle timing. The completed repeat used separate steps:
listener ready, operator confirmed supply off/LEDs off, then restored power on instruction and
confirmed it. The listener opened at 02:18:56 UTC and closed at 02:22:13 UTC, with no receive
buffer reset during the full sequence. It captured one byte before power-on confirmation
and six afterwards, but no valid startup telegram. Previous raw evidence is preserved.
This repeat reduces concern about missing startup solely because the listener opened late;
it does not establish an electrical fault's cause.

Implementation validation: **92 tests passed, 2 skipped** (hardware opt-in and POSIX-only)
on native Windows. Ruff formatting/lint and mypy passed; two pre-existing dependency
deprecation warnings remain. The installed console command and module both enumerate COM7.
The source audit and selected Windows query evidence are saved in
[windows-keyspan-20260907T020132Z.json](diagnostics/windows-keyspan-20260907T020132Z.json).

Install the local console entry point with `python -m pip install -e '.[dev]'`, then:

```powershell
lms200-hardware-diagnostic ports
lms200-hardware-diagnostic listen-startup --port COM7
lms200-hardware-diagnostic status --port COM7 --confirm-scanner-interface
lms200-hardware-diagnostic loopback --port COM7
```

The equivalent native module is `python -m lms200.hardware_diagnostic`. Each subcommand
accepts `--log PATH`, defaulting to `docs/diagnostics/hardware-raw.jsonl`. JSONL records are
**append-only** and tagged with UTC time, PID, run ID, mode and port. Existing evidence is never
truncated. Every RX chunk, including noise, is retained. Final results include serial state,
TX attempt and driver-accepted bytes, write return, flush result, full RX, ACK/NAK, frame offsets
(zero-based, end exclusive), payload lengths, computed/received CRCs, timeout and OS exceptions.
The initial default remains 9600/8-N-1. The 2026-09-08 fresh-start extension adds
`capture`, `--timeout`, `--raw-rx`, and separately confirmed host-only `--baud`
selection to capture/status/loopback. Status and capture CLI execution require
`--confirm-scanner-interface` after checking the current physical setup. No
scanner baud/configuration/streaming commands are added. See the
[fresh investigation and staged commands](FRESH_START_DIAGNOSIS.md).

### Passive startup capture

The listener opens COM7 and announces `listener_ready` before requesting a physical action.
It sends **zero bytes**, calls no input-buffer reset, and reads continuously while awaiting
operator confirmation. In an interactive terminal, press Enter **after** power is restored.
For orchestration use `--power-on-file NEW_PATH`: create that initially absent file only after
the operator confirms power restoration. A pre-existing file is rejected before opening.

The preparation window is bounded to five minutes. After the operator confirms power restored,
the listener allows 65 s: the manual's 60 s startup bound plus 5 s host margin. A valid `90`
startup frame completes capture early. The normal example starts `02 81 17 00 90`; the telegram
listing instead uses response address `80`. Both documented addresses are accepted, with exact
length and CRC validation. The ASCII model/firmware string and final status byte are preserved.
No received frame means no verified receive path; a confirmation timeout means **not tested**,
not a failed scanner startup.

The program closes on success, timeout, error, or Ctrl+C/SIGTERM. After a completed physical
startup capture, run only one authorized `status` command. Do not combine commands automatically
across an operator-confirmation boundary.

### Read-only status

The tool records the initial driver settings, control-line readings, and queue counts. It
preserves a short pre-TX sample, writes exactly `02 00 01 00 31 15 12` once, checks for seven
accepted bytes, and calls `flush()`. A one-second flush watchdog closes only this tool's handle
if output never drains. The three-second incremental receive window starts **after flushing**.
Queued pre-TX ACK/B1 data cannot complete the new request. Repeated ACK/noise cannot extend the
deadline. Success requires a preceding post-TX ACK and a complete matching B1 with valid CRC and
supported status layout. NAK and framed `92` rejection are logged; neither is success.

The shared pure framer now optionally exposes CRC candidates and received-stream offsets;
its normal frame/control API is unchanged. Stale partial candidates may be rescanned after
250 ms without data, but their raw bytes are always retained in the journal. The older
`lms200 probe-status` command remains available with its previously documented behavior;
use the new diagnostic command for flush and startup evidence.

### Adapter-only loopback (not yet authorized to execute)

Before performing any jumper action, explicitly confirm all four: scanner powered off;
Keyspan disconnected from the LMS cable; Keyspan connected only to the computer; safe
Keyspan DB9 **pin 2 to pin 3** connection. Do not jumper while connected to the scanner.
The command refuses to open a port until `--confirm-isolated-loopback` is explicitly supplied
after those confirmations. Its one binary pattern is:

```text
55 AA 00 FF 11 13 06 15 02 7E 80 01 FE A5 5A
```

It requires an exact echo, including the software-flow-control byte values, over a bounded
three-second window; extra bytes or an incomplete/mismatched echo fail. This checks the USB,
driver and adapter TX/RX path. It is not a scanner telegram and must never reach the LMS200.
The Keyspan Assistant's full external-loopback connector also links modem-control pins;
that is a different test. This no-flow-control data-only test uses **only 2-3**, as requested.

## Keyspan observations and optional Serial Assistant inspection

The manual associates slow flashing with idle, steady with a port in use, and rapid/random
flashing with TX and/or RX. A seven-byte request at 9600/8-N-1 takes about 7.3 ms on the line;
lack of sustained visible blinking is not a measurement of TX failure or a defective scanner.

The Windows manual's Diagnostics tab documents **Open Data Monitor Window** (also called
Line Monitor), showing data and modem-control changes, and **Open Driver Events Window**.
These can distinguish driver-visible TX and RX from a purely visual LED report. Availability
of those old UI labels in the installed 2024 package has not been checked. Do not start the
Assistant alongside a Python probe or bridge. End/close our port first, use the Assistant
alone for an independently authorized diagnostic, and close it before returning to Python.
Do not change port mappings, TX Ack Advance, handshake settings or drivers for this capture.

## Physical RS-232 inspection, only after power off and disconnection

The corrected SICK supplement and Keyspan male DB9 pinout establish:

| Scanner **data** connector | Keyspan DB9 |
| --- | --- |
| Pin 3 TxD | Pin 2 RX |
| Pin 2 RxD | Pin 3 TX |
| Pin 5 GND | Pin 5 GND |
| Pins 7 and 8 | Open on scanner; bridging selects RS-422 |

Connector fit does not establish crossover. Use molded pin numbers and documented viewing
direction: male/female, mating face and solder side can mirror numbering. Any opening,
continuity measurement or cable alteration requires the LMS200 powered off and disconnected.
Never apply power-pin assignments to the separate data connector.

## Interpretation and stop conditions

| Result | Interpretation / next boundary |
| --- | --- |
| CRC-valid startup `90` | Scanner-to-host RX path works; then test the one status request |
| ACK + CRC-valid B1 | Bidirectional communication verified; stop, no streaming |
| Write zero/short/exception or cannot open | Host/driver/ownership problem; stop and retain OS details |
| Write 7, no observed activity, RX 0 | Transmission accepted by driver; physical TX/RX still unverified |
| Loopback fails | Adapter/USB/driver/port configuration layer; stop |
| Loopback passes, scanner silent | Inspect crossover, ground, connector and RS-232 selection; stop before physical work |
| ACK only | Incomplete receive path, framing, timing or noise; preserve raw bytes |
| Bad CRC | Corruption/framing/CRC implementation needs review; preserve failed candidate |
| Startup works, status fails | TX path, addressing/command or receive/parser issue; not proof of a particular fault |
| Any next step needs power-cycle, disconnect, jumper or measurement | Pause for the operator's explicit confirmation |

## Sources read directly, 2026-09-06 EDT

- [SICK Quick Manual](https://www.danarte.es/archivos/pdf/1866.pdf): pp4-10 hardware, crossing, startup/status/defaults; pp12-14 output commands read for context only.
- [SICK Telegram Listing](https://sicktoolbox.sourceforge.net/docs/sick-lms-telegram-listing.pdf): pp21-24 framing/timing; p38 startup <=60 s; pp52-57 B1; p106 status; p107 CRC; p124 broadcast/defaults. p56 block B4 allows retained baud, qualifying the older quick manual's unconditional reset-to-9600 statement.
- [Corrected supplement](https://www.sick.com/media/docs/3/33/933/technical_information_lms200_211_221_291_laser_measurement_systems_en_im0027933.pdf): p3 Table 1-1 corrects scanner pins 3/4. Diagram visually checked.
- [Keyspan Windows v3.4 manual](https://www.dentinstruments.com/wp-content/uploads/2022/09/keyspan-19hs-instruction-manual.pdf): pp10-19 Assistant; p30 pinout/loopback; p31 LED; pp32-33 TX acknowledgement advance. DB9 diagram visually checked.
- [Current Eaton USA-19HS page](https://www.eaton.com/us/en-us/skuPage.USA-19HS.html): RS-232, up to 230 Kbps, manuals and Windows 10/11 driver link. Both supplied legacy `tripplite.eaton.com` URLs failed to load; this manufacturer page provides their current product/support resources.
- [Manufacturer Windows v3.7S manual](https://assets.tripplite.com/owners-manual/c2f630f2-61ce-40b8-8267-ef2523459d66.933021_usa-19hs_cu8713_mnl_rev_d.pdf): independent confirmation of pinout, LED, line monitor and 230 Kbps specification. No 500 kbaud or RS-422 test is permitted here.

Downloaded manuals remain in ignored `tmp/pdfs/`; they are not redistributed with the project.

## Direct connection test after operator-confirmed bare Keyspan loopback

This entry supersedes the earlier **current-state** statements that bare adapter loopback
was still pending. The operator confirms that bare USA-19HS loopback passed on COM7,
establishing the tested host/driver/adapter transmit and receive path. That confirmation
does not establish gray-cable wiring or scanner communication. Earlier raw logs, including
the separately named `isolator-loopback-raw.jsonl`, remain unchanged. The black Q.C. device
is the suspected port-powered RS-232 opto-isolator; its exact model is not verified here.

The operator explicitly confirmed all six direct-test prerequisites in this task:

1. LMS200 powered off.
2. Black opto-isolator removed.
3. Gray LMS200 cable connected directly to the Keyspan.
4. Connectors mated normally without force.
5. No pins jumpered.
6. PuTTY, SOPAS, serial terminals and all other COM7 programs closed.

Authorized connection: computer → USB → Keyspan USA-19HS → gray LMS200 data cable → LMS200.
These are operator confirmations, not remotely measured wiring facts. No unidentified adapter
may be added if connectors fail to mate normally; stop at that boundary.

### Revised native capture mode

`direct-test` fixes 9600/8-N-1 with all flow control disabled and requires
`--confirm-direct-connection`, a fresh `--power-on-file` and a separate fresh
`--startup-complete-file`. Create each marker only after its explicit operator reply.
Opening COM7 happens while the scanner is off. After `listener_ready`, ask the operator
to power on; keep reading through power-on and completed startup. The operator must confirm
yellow off and green or red alone. Allow at least 65 seconds after the power-on reply and
wait for startup-complete confirmation even if a valid startup frame arrived earlier.
Preparation and the wait for startup-complete confirmation each have a 300-second bound;
missing confirmation closes the port without sending status.

The same handle remains open from passive capture through the single status request, so
Windows pyserial's open-time purge is not repeated after power-on. No receive reset occurs.
Every received byte is retained in ordered `rx` events with offsets and UTC host-read
timestamps. Bytes in a single read share its timestamp; these are not wire arrival times.
Startup prefix sought: `02 81 17 00 90` (29 total bytes, 23-byte declared payload).
The existing documented `80` response-address profile remains available and is reported
explicitly if encountered. Only complete length/CRC-valid frames can establish a telegram.

After passive capture and operator confirmation, send only the seven binary status bytes
`02 00 01 00 31 15 12`. Record write return, bounded output flush and all received data for
**five full seconds after flushing**, including after an early ACK, NAK or complete reply.
Record standalone `06`/`15` separately from framed bytes, and require a preceding post-TX
ACK plus a length/CRC-valid matching B1 response for success. Never retry automatically.
The older separate `listen-startup`, `status` and `loopback` behaviors are preserved.

Interpretation: valid startup plus valid status verifies direct RS-232 and points to the
removed isolator as the likely problem. Valid startup alone calls for investigation of
Keyspan-to-LMS transmission/cable direction. Neither valid startup nor status means stop;
remaining likely causes under the requested test are gray-cable crossover, signal ground,
an LMS-side 7–8 RS-422 selection bridge, or LMS interface fault. These remain hypotheses
until measured. No continuous scanning is authorized by this test.

### 2026-09-06 23:03–23:08 EDT / 2026-09-07 03:03–03:08 UTC — direct test result

**No valid startup telegram and no status response. Stop; no retry or scanning.**
The direct connection and startup LED state were explicitly confirmed by the operator.
Removing the suspected isolator did not establish communication and does not identify it
as the sole cause. Its exact model and functionality remain unverified.

Native Windows Python 3.12.14 ran the guarded `direct-test` on COM7 at 9600/8-N-1,
`xonxoff=False`, `rtscts=False`, `dsrdtr=False`, DTR/RTS false. One handle remained open
from before the instruction to power on until after the single status request. There was
no receive-buffer reset or reopen after power-on. The record contains no OS exception.

| UTC timestamp | Recorded event |
| --- | --- |
| 03:03:46.954581 | COM7 open; passive listener ready, TX 0; operator then asked to power on |
| 03:07:36.479616 | RX `F0`, before the power-on confirmation marker |
| 03:07:48.777184 | Explicit operator power-on reply recorded; 65-second window started |
| 03:08:06.169356 | RX `39` |
| 03:08:06.170363 | RX `14` |
| 03:08:06.171356 | RX `31` |
| 03:08:06.172364 | RX `21` |
| 03:08:06.174322 | RX `31` |
| 03:08:06.175321 | RX `01` |
| 03:08:20.982196 | Operator startup-complete reply recorded: yellow OFF, green alone |
| 03:08:53.790866 | Passive capture ended, 65.014 s after power-on confirmation; total 306.844 s including preparation |
| 03:08:53.912993 | One binary status write attempted: `02 00 01 00 31 15 12` |
| 03:08:53.922660 | `write()` returned all 7 bytes |
| 03:08:53.932287 | Output flush completed, `out_waiting=0`; five-second read began |
| 03:08:58.933227 | Final result: no status RX; COM7 closed, no retry |

| Test | Bytes transmitted | Bytes received | ACK or NAK result | Valid frame result | CRC result | Interpretation |
| --- | --- | --- | --- | --- | --- | --- |
| Passive startup, isolator bypassed | 0 | 7: `F0 39 14 31 21 31 01` | Neither | None; no `02` STX or expected `02 81 17 00 90` header | Unavailable; no complete candidate | Input cannot be treated as an LMS200 telegram; receive path not established |
| Single read-only status | 7: `02 00 01 00 31 15 12` | 0 during 5.000 s post-flush read | Neither | No response | Request CRC `1215` valid (wire `15 12`); response CRC unavailable | Driver accepted/flushed the write, but no scanner exchange was verified |

No complete received frame existed for declared-length or CRC validation. The framer counted
seven non-frame bytes and zero telegrams; zero CRC errors does **not** mean CRC passed.
The status TX is binary (seven bytes), not ASCII hex. Write/flush alone does not measure
the signal delivered to the LMS200. The previously operator-confirmed bare Keyspan loopback
remains distinct evidence for the adapter/host transmit and receive paths.

Under the requested decision rule, stop here. Remaining likely causes to investigate in a
separately authorized physical step are gray-cable crossover wiring, missing signal ground,
an LMS-side 7–8 RS-422 selection bridge, or an LMS interface fault. None is established by
this capture. No configuration, baud change, settings-mode, laser-control, continuous-output,
cleanup stop telegram or automatic retry was sent. All physical changes require new explicit
operator confirmation; this test does not authorize further physical work.

Raw timestamped evidence: [direct-COM7-20260907T030336Z.jsonl](diagnostics/direct-COM7-20260907T030336Z.jsonl).
Run ID: `7491e0c4-f514-480e-b9b6-0f21e2c4fa45`; PID 53896 exited with code 1 for the
unsuccessful exchange. The record is complete and COM7 is closed. Historical captures are
preserved. Software validation before opening COM7: 101 tests passed, 2 skipped (physical
opt-in and POSIX), Ruff format/lint and mypy passed; two existing dependency deprecations.

## 2026-09-07 UTC — LMSAPI evaluation, offline only

The operator supplied LMSAPI 1.1c and confirmed the scanner powered off, reporting the
black adapter connected again. No current connector/wiring facts were inferred beyond
that report. No COM7 open, power-on instruction, physical change or new status attempt
was made. The preceding direct-test result and all raw evidence remain unchanged.

The new optional `python -m lms200.lmsapi_check` compiles and executes only the original
LMSAPI CRC function with a minimal modern ABI header, entirely offline. Both published
SICK vectors and 522 synthetic inputs match the project's CRC. Reinspection of the saved
direct-test bytes still finds no STX/complete telegram; it cannot yield a valid receive CRC.
This is a software comparison, not evidence of a newly successful scanner connection.

The full library's source configures on connect and retries automatically. Its Windows
serial writer overreports accepted bytes, its DCB retains flow-control flags, and its
receive parser requires address `80` instead of accepting the documented `81` profile.
It was not substituted into the hardware diagnostic or launched against the scanner.
Details, source locations, package hash and future physical boundaries are documented in
[LMSAPI_EVALUATION.md](LMSAPI_EVALUATION.md); executable comparison evidence is in
[lmsapi-offline-20260907.json](diagnostics/lmsapi-offline-20260907.json).

## 2026-09-07 03:57–03:59 UTC — explicitly authorized original LMSAPI experiment

After the offline audit, the operator explicitly authorized a separate backend retaining
LMSAPI's configuration-on-connect, internal retries and original parser/write limitations.
See [LMSAPI_EXPERIMENT.md](LMSAPI_EXPERIMENT.md) and ADR 0001 for this scoped exception;
the guarded production diagnostic retains its original defaults.

The operator confirmed scanner OFF, Keyspan → black adapter → gray cable → scanner,
normal connector fit, no jumpers/open scanner 7–8 and all other COM7 programs closed.
The original x86 DLL opened COM7 at 03:57:44.496 UTC; its passive listener was ready
before the instruction to power on. Separate operator replies confirmed power ON and
startup complete (yellow OFF, green alone). One handle remained open through the phases.

Passive DLL-reported RX was `C0 39 14 31 21 31 01`: seven bytes, no STX/complete frame
or CRC. After 65.011 seconds from power-on confirmation, one `lmsapi_open_terminal`
call requested 180°/0.5°/8 m/intensity off using the original configuration routine.
It logged **ten failed-read attempts**, then no sensor response, configuration-mode
entry failure and a null connection. The follow-up status call was **not attempted**.
The active call lasted about 12.90 seconds. No outer retry, baud search or scanning.

Active raw TX/RX counts, standalone ACK/NAK and wire CRC are **unavailable**, not zero
or passed: the original DLL hides them. No successful settings change was verified;
the absence of exposed active traffic also prevents proving that all settings stayed
unchanged. The library reported closed at 03:59:55.151 UTC; helper exited with code 3
and no runner process remained. No further hardware attempt is queued.

Raw exposed-byte/event/callback transcript:
[lmsapi-original-COM7-20260907035741Z.jsonl](diagnostics/lmsapi-original-COM7-20260907035741Z.jsonl).
Run ID `cfc45bcc-fe47-4379-b385-65856b697428`. This independent original-DLL attempt
did not establish communication and does not identify a particular cable/adapter/scanner
fault. Implementation validation: 123 tests passed, 2 skipped; Ruff and mypy passed.

## Explicitly requested repeated normal-backend status test

After the original LMSAPI experiment, the operator requested the normal serial backend
and repeated requests to obtain a scanner response or an LED change. The SICK-authored
[Quick Manual p9](https://www.danarte.es/archivos/pdf/1866.pdf) explicitly identifies the
startup `90` telegram as LMS → PC and recommends the PC → LMS status request for a link
test. The red LED denotes an infringement of a configured field; it is not a serial ACK.
No guessed LED command, field change, intentional fault or scanner reset is used.

New opt-in command (fresh log path required):

```powershell
.\.venv\Scripts\python.exe -m lms200.hardware_diagnostic status-repeat `
  --port COM7 --attempts 10 --confirm-repeated-status `
  --log docs/diagnostics/NEW-status-repeat.jsonl
```

This request authorizes up to ten **read-only** `02 00 01 00 31 15 12` writes on the
normal native pyserial path. It retains one COM7 handle, 9600/8-N-1, disabled hardware
and software flow control, and DTR/RTS false. It verifies each seven-byte write and
bounded output flush, then reads for five full seconds before considering another
request. No explicit RX reset/reopen occurs. Every returned byte and complete CRC
candidate is timestamped and retained; per-request offsets/results are included.

After the current five-second read, any post-request ACK, NAK or CRC-valid telegram
stops further sends. Success still requires a preceding ACK plus matching length/CRC-
valid B1 with supported status layout. Short writes, OS errors and interruption stop
the batch immediately. No request follows the maximum of ten, even on silence; this
does not create a background automation. Existing single-request modes are unchanged.

The last explicitly confirmed physical state is used: scanner powered on, startup
yellow OFF/green alone, Keyspan → black adapter → gray cable → LMS200, normal fit,
no jumpers/open scanner 7–8, other serial applications closed. The original LMSAPI
helper has exited. No physical change or power cycle is requested for this test.

### 2026-09-07 04:07–04:08 UTC / 00:07–00:08 EDT — repeated status result

**Ten read-only requests, no response. COM7 closed; repetition ended.** Native Windows
Python used the normal pyserial diagnostic, with the last confirmed powered-on scanner
and black-adapter connection. No further physical step or power cycle was assumed.

COM7 opened at 04:07:49.805 UTC and closed by the final record at 04:08:40.243 UTC.
Every request was the seven binary bytes `02 00 01 00 31 15 12`. All ten `write()` calls
returned 7; all ten bounded output flushes completed with output queue zero. Each
post-flush read lasted 5.000–5.047 seconds. The handle remained open throughout with
9600/8-N-1, `xonxoff=False`, `rtscts=False`, `dsrdtr=False`, DTR/RTS false and no explicit
RX reset. No OS exception occurred. No received byte existed to timestamp or decode.

| Test | Bytes transmitted | Bytes received | ACK/NAK | Valid frame | CRC | Interpretation |
| --- | --- | --- | --- | --- | --- | --- |
| Ten normal-backend status requests | Driver accepted 70 total: 7 per request | 0 throughout | Neither | None | Request `1215` verified; response unavailable | Repetition did not establish scanner communication |

Write/flush results establish driver acceptance, not an electrical measurement at the
scanner connector. The known successful bare Keyspan loopback remains separate evidence.
Zero CRC errors with zero frames is not a CRC pass. No startup telegram was transmitted;
no field/LED/fault/reset/configuration/baud/laser-control/continuous-output command was sent.
The green/red/yellow LED observation was requested from the operator but is not inferred
from the empty serial stream. No new LED observation had been confirmed when this entry
was written. No additional request is queued and the process exited with code 1 for the
unsuccessful exchange.

Evidence: [status-repeat-COM7-20260907040746Z.jsonl](diagnostics/status-repeat-COM7-20260907040746Z.jsonl).
Run ID `e4e0cfe2-4dfe-45fd-85e4-9db4b419cb2b`, PID 40932. Existing captures are preserved.
Verification before the run: 133 tests passed, 2 skipped; Ruff format/lint and mypy passed.

Operator follow-up: the user subsequently reported **no LED change** during the ten-request
batch. This is a visual operator observation, separate from the zero-byte serial capture.

### 2026-09-07 04:10 UTC / 00:10 EDT — explicitly requested single raw status capture

The operator then requested exactly `02 00 01 00 31 15 12` with raw hex capture and
ACK/frame/status/CRC inspection. The normal native pyserial diagnostic ran with
`status-repeat --attempts 1`: exactly one request and a full five-second post-flush
read, with no retry. The previously confirmed powered-on physical setup was used;
no new power cycle, disconnection or wiring change was requested or inferred.

COM7 opened at 04:10:20.874 UTC at 9600/8-N-1, all flow control disabled, DTR/RTS
false. At 04:10:20.997 the seven-byte binary request was submitted. `write()` returned
7 at 04:10:21.006; flush completed at 04:10:21.009 with `out_waiting=0`. The read window
lasted 5.000 seconds. Raw RX is **empty (`rx_hex=""`, zero bytes)**; no text decoding
or assessment of displayed characters was used.

| Test | Bytes transmitted | Bytes received | ACK/NAK | Valid frame / status | CRC | Interpretation |
| --- | --- | --- | --- | --- | --- | --- |
| Single status request | 7: `02 00 01 00 31 15 12`; write returned 7, flush completed | 0; raw hex empty | Neither `06` nor `15` | No STX/header/B1; no declared length to validate | TX `1215` valid, wire `15 12`; RX CRC unavailable | No communication established during this capture; no component failure identified |

COM7 was closed before the final record at 04:10:26.019 UTC; process exited code 1
for no response, with no OS exception. No reset, configuration, scanning or further
request was sent. The existing parser validates complete frame length and CRC, but
zero received bytes provide no frame to validate. Zero CRC errors is not a CRC pass.

Evidence: [status-single-raw-COM7-20260907041018Z.jsonl](diagnostics/status-single-raw-COM7-20260907041018Z.jsonl).
Run ID `f219f06f-2d8b-4a09-b27f-ad854d510c8c`, PID 58392. All preceding logs remain intact.

### 2026-09-07 — proposed visible-response experiment; NOT executed

The operator requested commands that could cause a visible scanner LED change.
The documented candidate is **one software reset**, not a direct LED-control telegram.
SICK Telegram Listing 8007954/Q501/2006-08-01, section 7.3, pp38–39 gives
`02 00 01 00 10 34 12` (seven binary bytes, CRC `1234`, wire `34 12`).
It restarts the scanner, **clears fault memory**, keeps the configured fields active,
and retains fatal-error history. Expected serial evidence is ACK, response `91`, then
startup response `90`, within the documented initialization period of up to 60 s.
Source: [official SICK Telegram Listing, pp38–39](https://www.sick.com/media/docs/3/03/003/telegram_listing_telegrams_for_configuring_and_operating_the_lms2xx_laser_measurement_systems_en_im0015003.pdf).

The Quick Manual p9 describes red/yellow during power-on startup. A similar visible
sequence after software reset is an **inference**, not a guaranteed LED-test behavior.
Source: [SICK-authored Quick Manual, p9](https://www.danarte.es/archivos/pdf/1866.pdf).
No LED change or accepted reset has been observed in this proposed experiment.

`python -m lms200.reset_experiment` performs **offline review only** by default, including
checking the published request CRC. The separate opt-in implementation is prepared;
normal diagnostic and production defaults are unchanged. Live execution is pending
explicit consent to fault-memory clearing and confirmation of the current powered-on
hardware state/closed competing COM7 applications. Earlier LMSAPI consent does not
authorize this reset. No COM7 handle was opened and no telegram was sent in preparation.

If authorized, the prepared command opens native Windows COM7 at 9600/8-N-1 with all
flow control disabled; listens before its single write; checks write count 7 and bounded
flush; preserves RX on the same handle; captures for 65 s after flush; records timestamped
raw bytes, standalone ACK/NAK, frame length and CRC; then closes. It accepts documented
80/81 response addresses and checks the reset/startup layouts. Short write/error stops;
there is no retry, follow-up command, baud change, field programming or stream request.
The operator's LED observation must be recorded separately from serial evidence.
Logs use exclusive creation in the existing diagnostics directory. Review invocation:

```powershell
.\.venv\Scripts\python.exe -m lms200.reset_experiment
```

Live flags, to be used **only after the explicit operator reply**:
`--execute --confirm-reset-clears-fault-memory --confirm-powered-on-hardware-unchanged
--log docs/diagnostics/NEW-reset-once.jsonl`.

### 2026-09-07 — flush and partial-read audit

The operator redirected the diagnostic to the read-only status request and asked for
the exact flush call. The reset proposal remains unexecuted and unapproved.

The diagnostic calls `flush_output(device)`, which invokes **`device.flush()`** under
a one-second watchdog. Installed pyserial's Windows implementation in
`.venv/Lib/site-packages/serial/serialwin32.py` waits while `self.out_waiting` is nonzero.
It does not purge received bytes. `reset_input_buffer()` discards RX, and
`reset_output_buffer()` aborts/discards TX; neither is called by this diagnostic.
`Journal` also calls `self.stream.flush()` to persist the log, which is unrelated to serial.
Reference: [pyserial API](https://pyserial.readthedocs.io/en/latest/pyserial_api.html#serial.Serial.flush).

Opening the port is a separate caveat: the installed Windows pyserial `open()` uses
`PurgeComm` on RX and TX. The diagnostic records bytes available **after open**, before
the request, and cannot recover bytes already discarded by that initialization. It
does not reopen or reset RX during the capture. Earlier startup tests armed the
listener before the operator powered on for precisely this reason.

The normal response decoder already accepts both `02 80` and `02 81` for broadcast
replies. The original LMSAPI DLL's 80-only parser is a separate implementation; an
output flush cannot repair its address check. Our raw logging precedes decoding, so
the earlier zero-byte status captures cannot be explained by header rejection.

The audit found and removed a diagnostic-only **250 ms idle-gap expiration**: although
all raw bytes were logged, it could discard the head of an incomplete parser frame
before the overall response timeout. Empty reads now leave the incremental buffer
intact until a complete length/CRC candidate arrives or the capture ends. The final
report retains an unfinished suffix. This changes neither the original DLL nor the
production state machine. Added synthetic regressions cover both addresses, splits
within STX/address/header/payload, a 600 ms gap, and a partial frame surviving the
entire timeout. Existing CRC-corruption, missing ACK, NAK and stale-reply checks remain.

Validation: 66 focused hardware-diagnostic/reset-experiment tests passed with simulated
serial devices; Ruff format/lint and mypy (27 source files) passed. Two whole-suite
attempts did not complete and were interrupted. The second captured a timeout stack
in the API dashboard/recording test (`tests/test_api.py:29`), with recorder worker
threads active; see local `tmp/flush-framing-suite.txt`. No full-suite pass is claimed.
Neither test process opened real COM7. The proposed reset was exercised only through
mocked serial objects; no live reset command was sent.

### 2026-09-07 04:21 UTC — one status request after partial-read correction

Following the operator's read-only test sequence, native Windows pyserial opened COM7
at 04:21:39.974 UTC using 9600/8-N-1, no flow control, DTR/RTS false. The last confirmed
powered-on Keyspan → black adapter → gray cable → LMS200 setup was used; no new
physical state or LED observation was inferred. The pre-TX sample recorded zero bytes.

Exactly one binary `02 00 01 00 31 15 12` request was attempted at 04:21:40.091 UTC.
The write returned 7; `device.flush()` completed at 04:21:40.104 with output queue zero.
The same handle remained open for 5.016 s of post-flush reading with no RX reset or
partial-frame idle expiration. Raw RX was empty. The process exited code 1 for no
response, with COM7 closed before the final event at 04:21:45.121 UTC.

| Test | Bytes transmitted | Bytes received | ACK or NAK result | Valid frame result | CRC result | Interpretation |
| --- | --- | --- | --- | --- | --- | --- |
| One status request, partial bytes preserved | 7 binary bytes; write returned 7, flush completed | 0 before TX and 0 after TX | Neither | None; no length/header/B1 to validate | TX `1215` valid; RX unavailable | Communication remains unverified; no received bytes existed for the parser to reject |

No retry, reset, baud change, configuration or continuous-stream request followed.
Raw evidence: [status-fragment-preserve-COM7-20260907042133Z.jsonl](diagnostics/status-fragment-preserve-COM7-20260907042133Z.jsonl).
Run ID `b8e34c92-3b59-4342-b793-f283a2c0efa7`, PID 59060. Earlier logs are preserved.

### 2026-09-08 18:21–18:23 UTC — guarded ROS 2 / LaViRIA status through Windows

The operator chose a guarded ROS 2 status experiment through the Windows Keyspan
driver because the current WSL kernel still lacks Keyspan support. Windows COM7
and the pinned LaViRIA source/artifact hashes were verified. This was a separate
ROS 2 diagnostic using original library message/CRC/send components, not the
unchanged scanning node; see [test guide](../tools/ros2_status/README.md).

Fresh confirmations established scanner OFF, black adapter absent, direct
Keyspan→LMS200 RS232 data connection, normal fit, no jumpers/open7–8, and other
COM7 applications closed. Both persistent readers were ready before the request
to power on. The operator separately replied `on`, then `green` to the startup
completion question. After 65.016 s from ON confirmation plus startup confirmation,
ROS 2 generated exactly one binary status request. Windows admitted only that
packet, with native write/flush evidence and no other scanner command.

| Test | Bytes transmitted | Bytes received | ACK/NAK | Valid frame result | CRC result | Interpretation |
|---|---|---|---|---|---|---|
| Passive startup | 0 | 0 | Neither | No startup frame | Unavailable | Startup receive path remains unverified |
| ROS 2 status | 7: `02 00 01 00 31 15 12`; Windows write 7, flush completed/queue 0 | 0 during 6.718 s after Windows flush | Neither | No B1/frame | Request `1215` valid; response unavailable | No communication established |

ROS 2 also saw zero bytes in its 6.010277 s post-send window. COM7/PTY closed;
ROS 2 and relay exited 3, Windows controller exited 1 for no exchange. There was
no serial API error, retry, configuration, baud change, reset, scan or cleanup
telegram. Counts remain driver-level observations, not electrical measurements.
No specific hardware fault was inferred. Windows/WSL wall clocks were offset;
monotonic elapsed windows and each raw journal are retained separately.

Validation: 642 C++ self-checks, 68 Python tests and both synthetic PTY/ROS 2
exchanges passed; 20 build-input/artifact hashes matched. Full results, hashes,
operator markers and raw logs are in
[the physical-run summary](diagnostics/ros2-status-COM7-20260908T182110Z/SUMMARY.md).
No run is queued and all earlier evidence is preserved.

### 2026-09-08 18:38–18:44 UTC — sequential Python, C++ and ROS 2 comparison

The operator requested multiple methods with persistent listeners and angle/other
operations, then selected Python, native C++ and ROS 2 sequentially, including
the native gated 100°/1° → ten-second continuous output → stop sequence. The
scanner was reported ON; the current startup/checklist prompt received `green`.
The earlier confirmed direct Keyspan→gray cable→LMS200 setup was retained. No
power or wiring change was requested or inferred.

| Test | Bytes transmitted | Bytes received | ACK or NAK result | Valid frame result | CRC result | Interpretation |
|---|---|---|---|---|---|---|
| Normal Python status | 7; write 7, flush complete/queue 0 | 0 over 5.000 s after flush | Neither | None | TX valid; RX unavailable | No exchange |
| Direct Win32 C++ | 21; three status writes, each count 7 and drain queue 0 | 0; post-drain windows 5.024/5.023/5.020 s | Neither | None | TX valid; RX unavailable | Separate ReadFile worker stayed healthy throughout, but no reply |
| ROS 2 / LaViRIA status through Windows | 7; Windows write 7, flush complete/queue 0 | 0 over 6.110 s Windows post-flush (6.032336 s ROS 2 post-send) | Neither | None | TX valid; RX unavailable | No exchange |
| Native angle/start/stop stages | 0 | Not attempted | Not applicable | Not applicable | Not applicable | Status/ACK gate failed; these commands were not sent |

All five requests were binary `02 00 01 00 31 15 12`, totaling 35 driver-accepted
bytes. All pre-TX captures were empty too. Each backend held one COM7 handle for
its whole run and closed before the next; this was not one shared handle across
backends. All physical I/O used native Windows 9600/8-N-1, no flow control. The
native reader remained active through writes/drain; Python reads pause during
synchronous write/flush while Windows buffers incoming bytes. No application RX
reset occurred after initial open. No serial/read failure or specific hardware
fault was established. Driver counts do not prove electrical transmission.

ROS 2 now has an explicit already-powered-on checklist option, tested separately
from the original OFF/startup/65-second flow. It waits for both readers and
pre-TX capture, admits one status only and creates no power/startup marker files.
No production defaults or original third-party binaries were changed. Validation:
76 native checks, 78 focused Python tests, 642 ROS 2 C++ self-checks, Ruff/mypy and
all recorded build hashes passed. Windows/WSL clocks remain offset; receive
durations use each process's monotonic clock. All handles/PTY/relay closed; no run
is queued. Raw logs, exact confirmations and full details are in the
[comparison summary](diagnostics/method-comparison-COM7-20260908T183745Z/SUMMARY.md).
