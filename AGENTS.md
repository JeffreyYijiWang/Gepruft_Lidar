# LMS200 project guide

Native C++ experiment requested 2026-09-07: `tools/lms200_native` is a separate
direct-Win32 COM7/9600/8-N-1 diagnostic. The user authorizes status, optional
100-degree/1-degree variant, continuous output, ten seconds after confirmed start,
then stop, but requires fresh powered-on/startup-complete/other-COM7-apps-closed
confirmation and the optional-variant choice before live execution. No wiring
change. Offline build/checks precede confirmation. Preserve one reader/handle,
raw-before-parser evidence and bounded stop cleanup. This scoped exception does
not change production Python defaults or authorize unrelated commands. See
tools/lms200_native/README.md and ADR 0001. No live native C++ run has occurred
as of this preparation entry.

Native C++ live result 2026-09-07 05:24 UTC: operator freshly confirmed powered ON,
startup complete, other COM7 apps closed, and selected optional 100-degree/1-degree.
All 59 offline checks passed; source/executable SHA256 matched the archived manifest.
One exclusive Win32 COM7 handle configured/read back 9600/8-N-1, all flow control
off including DSR sensitivity, DTR/RTS disabled. Reader armed before TX; one status
`02 00 01 00 31 15 12`, Windows completion count 7, output queue zero. Reader failed
with `ClearCommError` Win32 error 5 after 563 ms post-drain; RX 0 in that shortened
window, no ACK/NAK/frame. No variant, start, capture, or stop command was reached;
port closed, exit 3, no retry. Cause of API access denial unknown. Subsequent
read-only outside-sandbox PnP inspection listed COM7 OK; it did not open serial.
Do not equate this shortened capture with a full timeout or a hardware fault.
Evidence: docs/diagnostics/native-COM7-20260907T052445Z/SUMMARY.md. No run queued.

User subsequently requested fixing error 5, keeping a listener open and rerunning
the bounded native sequence, and auditing htons/ntohs/byte swapping/struct writes.
Same original executable ran outside the sandbox at 05:33 UTC: one reader stayed
open ~15 s, three status writes each Windows-count7 and queue0, post-drain windows
5027/5042/5003 ms, RX0, no error5/read failure. Status was not confirmed; no variant,
start, capture or stop was sent; handle closed, exit3. This supports an execution-
context explanation but does not prove the permission mechanism or scanner fault.
Evidence: docs/diagnostics/native-outside-sandbox-COM7-20260907T053317Z/SUMMARY.md.
Native query-error fix now separates ClearCommError/modem observation availability
from actual ReadFile failures; null unavailable values never confirm drain. Primary
read failures are recorded before optional queries. `--listen-only` is an explicit
ten-second no-TX capture, exclusive with the variant flag, and closes at deadline.
Byte-order audit found no network-order conversions or struct-to-serial writes in
active native/Python/bridge paths. Docker does not itself swap telegram bytes.

Corrected native reader run 2026-09-07 05:43 UTC, outside sandbox: 76 offline checks
passed; all build-input/executable hashes matched. One COM7 reader stayed healthy
through three status writes/count7/queue0 and 5024/5024/5010 ms receive windows.
RX0, no ACK/NAK/frame, no ClearCommError or read failure. Status failed; optional
variant/start/capture/stop were not attempted. Handle closed, exit3, no run queued.
Evidence: docs/diagnostics/native-reader-fix-COM7-20260907T054336Z/SUMMARY.md.
Both original and corrected native binaries completed outside-sandbox reception
without access denial; exact cause of earlier denial remains unproven. Missing
scanner replies are unresolved. Do not bypass status/ACK gates or infer hardware
fault, electrical silence, or physical TX from these driver-level observations.

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
Manual discrepancies are explicit profiles, not heuristics: B1 data lengths 146/152
(six reserved bytes corroborated by SICK Toolbox), config lengths 32/34, and 814-byte
maximum telegram with optional indices. See docs/PROTOCOL.md and references/README.md.
Environment numeric Literal settings must be converted from strings before validation;
keep the Compose startup regression test. Record workers own their recorder/queue arguments.

Physical commissioning authorization: user confirmed Keyspan USA-19HS, RS-232 only,
fixed 9600 8-N-1, one status request; no configuration or continuous output. Pins 7–8
remain open; no RS-422/500000. Current native tool is `lms200-hardware-diagnostic`
with ports/listen-startup/status/loopback. Never use the broader `probe` (type/config/baud search).
The new status command preserves RX and logs one write plus bounded flush, then listens 3 s.
Legacy `lms200 probe-status` still exists but clears RX and does not flush; see audit.
Passive startup sends nothing; arm before the operator power-cycles. Wait for explicit physical
confirmation; no automatic reset. Allow 65 s after confirmed power restoration, max 300 s
preparation. Loopback requires scanner off, scanner cable disconnected, USB-only Keyspan,
and explicit confirmation of its DB9 2-3 link before `--confirm-isolated-loopback` may be used.
No simultaneous Serial Assistant/Python/bridge owners. Stop before unconfirmed physical work.
After driver installation, Windows assigned Keyspan COM7. Physical probe 2026-09-06
21:49 EDT opened/closed COM7 at 9600 8-N-1; TX 02 00 01 00 31 15 12 (7 bytes),
RX 0 bytes, no ACK, timeout. No retry, baud change, configuration, or scanning was sent.
After a slow-flashing adapter LED report, a fresh native status attempt at 21:54 EDT
again opened/closed COM7, TX 7 bytes, RX 0, and timed out at the 250 ms ACK deadline.
User subsequently reported the scanner's green LED. At 21:57 EDT, a new one-request
attempt listened for a full 3 s: COM7 opened/closed, TX 7 bytes, RX 0, no ACK/response.
The diagnostic probe now waits 3 s even without ACK, logging elapsed listening time;
normal service timeouts are unchanged. No configuration or scanning was enabled.
Windows audit 2026-09-07 02:01 UTC: COM7 parent USB VID06CD/PID0121, both signed KSPN
drivers OK/error 0. Seven-byte write return is driver evidence, not proof of signals at DB9.
At 22:14 EDT, passive capture spanning an operator-confirmed power cycle received
`10 04 21 00 28 01 A0` only (no STX/startup frame/CRC). The subsequent single status
write returned 7 and flush completed/out_waiting 0; RX 0 in 3.031 s, no ACK/NAK.
Both COM7 handles closed. Isolated loopback and cable crossover remain unverified;
stop before further physical work and obtain explicit off/disconnected/jumper confirmation.
User questioned the first power-cycle timing and requested a repeat. At 22:18-22:22 EDT,
listener stayed open across separately confirmed OFF/LEDs-off and ON steps: RX
`00 39 14 31 21 31 01`, no valid frame. Subsequent single status TX 7, write return 7,
flush completed, RX 0 in 3.015 s; both handles closed. Offline checks confirm real binary
bytes (not ASCII hex), correct request CRC, and valid 29-byte manual startup example CRC.
Operator now confirms physical isolation: LMS200 powered off, black Q.C. adapter and gray
LMS200 cable removed, only Keyspan connected to USB, DB9 pins exposed. COM7 re-enumerated.
No pin 2-3 jumper has been confirmed yet; do not run loopback until that explicit reply.
Later operator-confirmed finding: bare Keyspan USA-19HS loopback passed on COM7, superseding
the preceding pending-loopback state. Do not repeat it as a prerequisite. The gray cable
and scanner link remain unverified. Use native `direct-test` for the authorized isolator
bypass: require all six physical confirmations (scanner off, isolator removed, gray cable
direct, normal connector fit, no jumpers, other COM7 owners closed). Keep one COM7 handle
open across passive startup and one status write; no RX reset/reopen after power-on.
Separate explicit power-on and startup-complete replies gate progress. Capture at least
65 s after power-on confirmation and wait for startup-complete confirmation, then one binary
status request with write/flush evidence and a full 5 s post-flush read. No automatic retry.
Exact isolator model and cause remain unverified. Preserve historical logs.
Direct bypass test 2026-09-06 23:03–23:08 EDT: operator confirmed all six conditions and
later power ON, then yellow OFF/green alone. Same COM7 handle stayed open throughout.
Passive RX `F0 39 14 31 21 31 01` (7 bytes, no STX/valid frame); after 65 s from power-on
confirmation, one status TX `02 00 01 00 31 15 12`, write return 7, flush completed/queue 0,
RX 0 over 5.000 s, no ACK/NAK/response CRC. COM7 closed; no retry/scanning/configuration.
Evidence: docs/diagnostics/direct-COM7-20260907T030336Z.jsonl. Bypassing the isolator did
not establish communication; cable crossover, signal ground, LMS-side interface selection
and interface fault remain unverified possibilities. Stop before further physical work.
MST research 2026-09-07 UTC: original demo ZIP not located; documentation only, retained in
git-ignored third_party/sick_mst/. See docs/MST_DEMO_RESEARCH.md for sources and SICK request.
The requested Quick Manual for MST Demo setup is v1.0 August 2002 (distinct from the June
2001 communication manual): installation p9, connection p10, recorder/configuration pp11–13.
It names MSTDemo.exe and says starting MST automatically uses the highest possible baud;
the recorder applies configuration and records scans. Do not treat it as a fixed-9600,
read-only probe. COM7 support, Windows 11 compatibility, binary bitness and source license
remain unverified. No vendor software executed or COM7 opened during this research.
LMSAPI 1.1c evaluation 2026-09-07 UTC: see docs/LMSAPI_EVALUATION.md. Optional
`python -m lms200.lmsapi_check` builds/runs only reviewed CRC source offline; both manual
vectors and 522 synthetic inputs match our CRC. No COM7 open or live LMSAPI test occurred.
The included full-library source configures on connect, retries up to 10 times, accepts
only response address 80, inherits flow-control flags and overreports write counts.
Do not replace the guarded diagnostic with it. Original DLL is x86; CRC-only rebuild x64.
Third-party ZIP/source/build stay ignored in third_party/lmsapi/; production driver unchanged.
Later explicit authorization: user requested original LMSAPI as a separate experiment,
including its configuration-on-connect, internal retries, write-count defects and 80-only
parser. This supersedes the earlier status-only restriction only for `lmsapi_experiment`;
see docs/LMSAPI_EXPERIMENT.md and ADR 0001. Original x86 DLL runs in a separate Windows
helper, with fresh physical/power/startup gates, fixed COM7/9600 and 90 s active watchdog.
Planned connect arguments: 180 degrees, 0.5 degree resolution, 8 m range, intensity off;
one outer connect then status call, native internal retries retained, no scanning/outer retry.
Operator confirmed scanner OFF, Keyspan > black adapter > gray cable > LMS200, normal
fit, no jumpers/open scanner 7–8 and all other COM7 owners closed. Do not infer power ON.
Original DLL offline x86 self-test passed CRC 1215 with serial closed. Active raw TX/RX,
standalone ACK and wire CRC are not exposed; report these as unavailable, never zero/pass.
Original LMSAPI live result 2026-09-07 03:57–03:59 UTC: operator separately confirmed
power ON then yellow OFF/green alone. Original DLL passive RX C0 39 14 31 21 31 01;
no STX/frame/CRC. After 65.011 s, one open_terminal call logged ten failed-read attempts
and configuration-mode entry failure, returned null; follow-up status not attempted.
COM7 closed and helper exited code 3. Active wire counts/ACK/CRC and accepted settings
are unknown. No outer retry or scan. No test queued. See docs/LMSAPI_EXPERIMENT.md.
Transcript: docs/diagnostics/lmsapi-original-COM7-20260907035741Z.jsonl.
Subsequent user request authorizes repeated normal-backend communication requests.
Use opt-in `status-repeat --attempts 10 --confirm-repeated-status`: at most ten binary
31 status requests, full 5 s after each flush, same native pyserial handle/no RX reset.
Stop further sends on ACK, NAK, CRC-valid telegram, short write, error or interruption.
Single-request defaults remain unchanged. Startup 90 is scanner-to-host, never a host
request. QM p9 says red indicates an infringed configured field, not a serial ACK;
do not substitute an invented LED/error command. No field/config/laser/reset commands
are part of this repeated read-only test. Last operator-confirmed setup remains powered
ON, startup yellow OFF/green alone, Keyspan > black adapter > gray cable; no new physical
step is requested or assumed. Original LMSAPI helper has exited and released COM7.
Repeated normal pyserial status result 2026-09-07 04:07–04:08 UTC: one COM7 handle,
ten binary 31 requests, each write returned 7 and flush completed/output queue zero;
70 driver-accepted TX bytes, RX 0, no ACK/NAK/frame/response CRC. Each post-flush read
lasted at least 5 s. Port closed, process exited; no follow-up batch queued. No config,
LED/field/fault/reset/baud/laser/stream command was sent. LED change not inferred.
Evidence: docs/diagnostics/status-repeat-COM7-20260907040746Z.jsonl.
Operator subsequently reported no LED change during that ten-request batch.
At the user's next explicit request, single raw status capture 2026-09-07 04:10 UTC:
COM7 normal pyserial 9600/8-N-1; one binary 31 write returned 7, flush completed,
RX hex empty over 5.000 s, no ACK/NAK/B1/frame/response CRC. COM7 closed, no retry.
Evidence: docs/diagnostics/status-single-raw-COM7-20260907041018Z.jsonl.
Visible-response research: TL section 7.3 pp38–39 documents software reset bytes
`02 00 01 00 10 34 12`; CRC checked offline. Reset clears fault memory, retains fatal-error
history and configured fields. A startup LED sequence is inferred, not guaranteed.
Separate `python -m lms200.reset_experiment` defaults to offline review only; explicit
fault-memory-clear consent and current hardware confirmation are pending. Do not run
its live flags without that reply. No COM7 open or reset occurred during preparation.
See the proposed visible-response experiment in docs/HARDWARE_DIAGNOSTIC.md.
Partial-read audit: normal pyserial decoder already accepts response addresses 80/81.
Its serial flush is `device.flush()` (wait for TX queue), distinct from RX/TX buffer
reset calls. Installed Windows pyserial purges during open; pre-TX capture records
bytes available after that point. Capture no longer expires incomplete frames after
a 250 ms idle gap; preserve them across empty reads through the overall timeout.
Raw logging occurs before parsing. The original LMSAPI DLL remains unchanged.
After that correction, one user-requested normal status attempt at 2026-09-07 04:21 UTC:
COM7 9600/8-N-1, pre-TX RX 0, write returned 7, output flush completed/queue zero,
post-TX RX 0 over 5.016 s, no ACK/NAK/frame/response CRC. COM7 closed, no retry/reset.
Evidence: docs/diagnostics/status-fragment-preserve-COM7-20260907042133Z.jsonl.
TL p56 permanent-baud option qualifies QM's default-9600 startup statement; still test only 9600.
Read docs/HARDWARE_DIAGNOSTIC.md for source-verified wiring, tool audit and operator boundaries.
See docs/HARDWARE_DIAGNOSTIC_LOG.md and docs/diagnostics/ for physical evidence.
Operator confirmed external power, connector identification, open 7–8 pins, and completed
startup. Memory Integrity is running. The official driver downloaded below has 2024-12-06
release notes explicitly supporting Memory Integrity; older incompatibility advice is obsolete
for that release. Keep security settings enabled. User authorized native Windows installation;
MSI completed successfully on 2026-09-06. Driver Store now contains Microsoft-signed
KSPN USB 19h.inf 17.14.44.557 and Ports 19hp.inf 17.14.44.551 (2024-08-16).
Re-enumerate after reconnecting; COM7 is the observed port, not a universal assignment.
Official download: https://assets.tripplite.com/drivers/usa-19hs_win11_win10_driver.zip .

Manuals (accessed 2026-09-06; full index and contradictions: docs/references/README.md):
* https://www.sick.com/media/pdf/3/43/843/dataSheet_LMS200-30106_1015850_es.pdf
* https://www.sick.com/media/docs/3/33/933/technical_information_lms200_211_221_291_laser_measurement_systems_en_im0027933.pdf — §1.1 p3 corrected data pinout.
* https://www.danarte.es/archivos/pdf/1866.pdf — pp4–12 power/wiring/setup; p12 up to 7 s configuration; p14 stop.
* https://sicktoolbox.sourceforge.net/docs/sick-lms-telegram-listing.pdf — §4 pp21–25 framing/timing; §7.4 pp40–45 modes/baud; §7.5 pp47–51 scans/origin; §7.6 pp52–57 status; §7.15 p65 model; §7.16 p66 variant; §7.43 p90 config read; §7.46 pp96–102 config write; §8 p106 status; §9 p107 CRC; §10.8 p124 overflow.

SickToolbox offline preparation 2026-09-07: user reports disconnected and explicitly
requests preparation only, no runs. Pinned ros-drivers SickLMS2xx library/examples and
LaViRIA ROS 2 Jazzy candidate compile in WSL; sources unchanged, no driver executed.
See docs/SICKTOOLBOX_READINESS.md and tools/sicktoolbox_offline/. ROS 1 wrapper is
reference only. These builds are not live-qualified: payload bounds, 80-only parser,
hidden baud search, and ROS 2 no-op stop require review. Current WSL kernel config
has CONFIG_USB_SERIAL_KEYSPAN unset. No USB attachment or live test is queued.
Follow-up imports the exact LaViRIA SDK and ROS 2 package into .local/laviria_lms200;
tools/sicktoolbox_offline/README.md is the next-session guide. check-laviria.ps1
checks source/artifact hashes and ROS metadata only; it must not launch hardware.

ROS 2 Windows-bridge test preparation 2026-09-08: user selected a guarded status
test through the native Windows Keyspan driver. Current offline checks verified
the pinned LaViRIA SDK/node hashes and ROS metadata; WSL kernel 6.18.33.2 still
has CONFIG_USB_SERIAL_KEYSPAN unset. Windows lists Keyspan COM7 OK, USB 5-1 not shared.
Operator reports scanner OFF, black adapter absent, direct Keyspan→LMS200 RS232;
separately confirms normal fit, no jumpers/open7–8 and all other COM7 apps closed.
tools/ros2_status is a separate ROS2 diagnostic using original library message/CRC
and send components, not the unchanged scanning node. One Windows COM7 owner uses
anonymous pipes/WSL PTY; one exact status packet only, no Initialize/baud/scan/reset.
Do not infer power ON: both listeners must be ready before asking, then explicit
ON/startup-complete replies plus65s gate TX. See tools/ros2_status/README.md and ADR0001.
ROS2 Windows-bridge live result 2026-09-08 18:21–18:23 UTC: both readers armed while
OFF; operator replied ON, then green to startup-complete prompt. After65.016s,
one original-library binary status reached Windows: write7, flush complete/queue0.
Passive RX0; status RX0 over6.718s Windows post-flush and6.010277s ROS2 post-send.
No ACK/NAK/frame/responseCRC or serial API error. COM7/PTY and relay closed; Windows
exit1, ROS2/WSL exit3 for no exchange. No retries/baud/config/reset/scanning sent.
642 C++ self-checks,68 Python tests,two synthetic PTY exchanges and20 build hashes
passed. Evidence: docs/diagnostics/ros2-status-COM7-20260908T182110Z/SUMMARY.md.
Windows/WSL clocks had an offset; use each process's monotonic duration. Do not
infer electrical TX, specific hardware failure, or a new LED observation. No run queued.

Sequential comparison 2026-09-08 18:38–18:44 UTC: operator selected Python, native
C++ and ROS 2, including gated 100°/1° then 10 s output/stop; scanner reported ON
and startup reply `green`, previous direct wiring retained. Python one status:
7 TX/RX 0 over 5.000 s; native three statuses: 21 TX/RX 0 over 5.024/5.023/5.020 s
with healthy independent reader; ROS 2 one status: 7 TX/RX 0 over 6.110 s Windows
and 6.032336 s ROS 2. Every Windows write counted 7 and drain/flush completed
with queue 0. No ACK/NAK/frame;
variant/start/stop not reached. Each backend kept its handle throughout its run,
then closed before the next. All closed, no run queued; no hardware fault inferred.
ROS 2 now supports an explicit mutually exclusive powered-on checklist mode that
waits both readers/pre-TX capture without power/startup marker fabrication. The
original OFF/65 s path remains. 78 focused Python tests, 76 native checks, 642 ROS 2
checks and build hashes passed. See docs/diagnostics/method-comparison-COM7-20260908T183745Z/SUMMARY.md.

Commands: `python -m pip install -e '.[dev]'`; `ruff format --check .`; `ruff check .`;
`mypy`; `pytest -q`; `lms200 serve --transport simulator`; `docker compose up --build`.
Windows verification: `./scripts/verify.ps1`; POSIX: `sh scripts/verify.sh`.
Tests need no hardware; golden vectors must cite exact manual examples, synthetic fixtures
must say so. Include fragmented/noisy streams, NAK/timeouts, shutdown, bridge loopback,
replay and API/WebSocket integration. Hardware tests remain opt-in. Do not redistribute PDFs.
