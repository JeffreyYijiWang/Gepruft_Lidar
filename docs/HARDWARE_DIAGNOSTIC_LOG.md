# Physical hardware diagnostic log

## 2026-09-06 — first Keyspan preflight, Windows host

**Physical status exchange could not start: the Keyspan has no installed driver or COM port.**
No serial handle was opened and no hardware telegram was transmitted. These are physical
Windows inventory results, separate from simulator and fake-serial test results below.

### Operator confirmations

The user identified a **Keyspan USA-19HS** and authorized **RS-232 only, fixed 9600 8-N-1,
one status request**. The user separately confirmed all four remaining checks: correct external
24 V supply connection, positively identified power/data connectors, scanner data pins 7–8
open, and completed scanner startup. These are operator confirmations, not remotely measured
wiring or voltage readings. No additional baud attempts, configuration, or scanning is authorized.

### Windows observations

Read-only `Win32_SerialPort`, present Ports devices, and `Win32_PnPEntity` inventory showed:

| Item | Observed value |
| --- | --- |
| OS | Microsoft Windows 11 Home, 64-bit, version 10.0.26200 |
| USB device name | `Keyspan USA-19H ` (Windows includes a trailing space) |
| USB hardware ID | `USB\VID_06CD&PID_0121` |
| Vendor/product IDs | `06CD` / `0121` |
| Manufacturer field | Unavailable/null in Windows inventory |
| Adapter model | USA-19HS, confirmed by user; Windows descriptor says USA-19H |
| Electrical standard for this test | RS-232, confirmed by user |
| Windows device status | Error |
| ConfigManagerErrorCode | **28** |
| Driver service | Unavailable/null |
| Keyspan COM port | **None assigned** |
| Other present COM ports | COM3 and COM4, both Standard Serial over Bluetooth link; neither used |

Microsoft defines [Code 28](https://learn.microsoft.com/en-us/windows-hardware/drivers/install/cm-prob-failed-install)
as device drivers not installed. USB enumeration therefore succeeds, but serial access is not
available. This does not establish a scanner fault or incorrect wiring.

### Physical probe result

| Requested result | Actual result |
| --- | --- |
| Port opened | No; no Keyspan COM port available |
| Serial handle left open | None |
| Transmitted bytes | **0** |
| Received bytes | **0** |
| Raw TX hexadecimal | Empty; nothing transmitted |
| Raw RX hexadecimal | Empty; nothing received |
| Response CRC expected / received | Unavailable; no response |
| Response address / command / status | Unavailable; no response |
| Device type, firmware, active baud | Unavailable from hardware |
| Units, measuring mode, FOV, angular resolution | Unavailable from hardware |
| Scanner warning/error flags | Unavailable; scanner communication was not attempted |

The **planned, untransmitted** request is `02 00 01 00 31 15 12`: seven bytes, broadcast
address 00, payload length 1, command 31, CRC word 1215 (wire order 15 12). Its CRC is
covered by the existing independent manual golden-vector test. This is not a physical TX log.

### Driver compatibility investigation

[Eaton's official USA-19HS support page](https://www.eaton.com/us/en-us/skuPage.USA-19HS.html)
lists a Windows 10/11 driver. Its
[USA-19HS product document](https://tripplite.eaton.com/shared/product-pages/en/USA19HS.pdf)
had an indexed older version stating that this adapter is incompatible with Core Isolation /
Memory Integrity enabled. **This advice was superseded by the updated driver release notes
obtained below; it must not be applied to the downloaded 2024 driver.**

This PC reported `SecurityServicesConfigured=[2]`, `SecurityServicesRunning=[2,7]`, and
`VirtualizationBasedSecurityStatus=2` through `Win32_DeviceGuard`; the HVCI Enabled registry
value was also 1. Microsoft's [field definitions](https://learn.microsoft.com/en-us/windows/security/hardware-security/enable-virtualization-based-protection-of-code-integrity)
identify running service 2 as Memory Integrity. No driver-install attempt was made, so no
installation failure caused by HVCI was observed. Memory Integrity is not an established
blocker for the updated compatible driver.

Two attempts to download the ZIP linked by Eaton failed with connection reset, including an
approved download outside the sandbox. No installer was executed, no driver signature was
verified, and no Windows security setting was changed. The present Code 28 is the confirmed
immediate blocker; driver compatibility is a separate prerequisite for proceeding.

### Software preflight and correction

The ordinary `lms200 probe` reads 31, 3A, and 74, and normally searches baud rates. It was
not appropriate for this narrower authorization. Added `lms200 probe-status --port COMx
--log NEW.jsonl`, which runs natively on Windows and:

* Fixes the host port at RS-232 9600 8-N-1 with flow control disabled.
* Clears stale input and sends exactly one documented 31 status request.
* Logs the requested transmission, driver-accepted TX count/hex, every RX chunk, validated
  frame CRC/status, and final result to a new JSONL file; also prints TX/RX hex to the console.
* Requires ACK plus B1; validates framing, address, length, status, and documented CRC.
* Uses the established 250 ms ACK deadline with USB margin and 3 s post-ACK response policy.
* Does not retry, detect/change baud, query model/configuration, transmit a password, send a
  cleanup stop, or start continuous output. Closing a timeout does not change scanner settings.
* Closes on success, NAK, timeout, malformed response, read failure, or SIGINT; SIGTERM also
  routes through cleanup. Settings environment variables do not affect this command.

The exact model remains unknown after a status-only exchange because the separate BA model
query is intentionally omitted; the final response status identifies device type when available.
Unsupported B1 layouts preserve raw evidence and fail rather than guessing decoded values.

Validation: initial requested protocol/CRC/framing/measurement/state-machine/simulator suites
passed **41 tests**. The new fake-serial suite passed **14 tests**, including real Python SIGINT
delivery during a mocked serial read. Final native verification passed **66 tests, 2 skipped**
(physical opt-in and POSIX PTY); Ruff format/lint passed and mypy passed for 23 source files.
Two existing upstream Starlette/AnyIO deprecation warnings remain. No test used the Keyspan.

### Next required action

Resolve the Windows serial-driver compatibility issue before assigning or opening a COM port.
Use the updated Memory Integrity-compatible driver downloaded below. Disabling a Windows
security feature is unnecessary according to its release notes and is outside this task.

Once Windows reports the Keyspan serial port as healthy, re-identify that port and execute only
the prepared single-status command. The operator confirmations above remain recorded; do not
ask for them again unless the physical setup changes. The current execution environment is
native Windows Python; if the test is later run from Docker, use the native bridge instead of
attempting direct COM mapping. No approval to configure or stream has been given.

## 2026-09-06 — official driver downloaded; LED explanation

At the user's request, downloaded the Windows 10/11 package successfully from Tripp Lite's
[official asset server](https://assets.tripplite.com/drivers/usa-19hs_win11_win10_driver.zip).
This endpoint was linked by Columbus McKinnon's equipment-support download page and avoids
the repeatedly reset Eaton website download endpoint.

Local archive: `tmp/USA-19HS-Windows-10-11.zip`.
SHA-256: `b66bb71957994fcdedc432a8625dce0ba22408bb16c62a485d69fea6fcd0bc05`.
Extracted directory: `tmp/keyspan-official-driver/USA-19HS Win11 Win10 Driver - 2024-12-16/`.
The package includes a release-notes PDF and the `USA-19HS Installer - 2024-11-10` folder
containing `USA-19HS Driver Installer.msi` and `setup.exe`.

**Correction:** The enclosed *KeySpan USA-19HS Installer Release notes*, dated 2024-12-06,
explicitly state that the new drivers support Windows Memory Integrity. They describe how old
incompatible driver copies can persist in the Windows Driver Store, and how the updated installer
handles those copies. The earlier incompatibility conclusion was based on outdated indexed
product information. Keep Memory Integrity enabled when using this updated release.

The release notes direct the operator to detach the USB adapter before installation, run the
MSI, then reconnect the adapter after installation. Existing Keyspan software may need removal
as described in those notes; no uninstall was attempted here. The wrapper EXE and MSI returned
`NotSigned` from Get-AuthenticodeSignature. This is a check of the installer wrappers, not the
embedded driver catalogs; it does not establish the drivers' signing status. No installer has
been executed and no security setting or scanner configuration has been changed.

The user reported an absent/nonflashing adapter LED. No remote visual confirmation was made.
The [official USA-19HS manual](https://assets.tripplite.com/owners-manual/c2f630f2-61ce-40b8-8267-ef2523459d66.933021_usa-19hs_cu8713_mnl_rev_d.pdf)
p4 describes: off = no USB connection/power or incorrect installation; slow blink at about
one per second = normal idle; steady = port in use; rapid/random blink = serial data activity.
Because Windows enumerated this adapter earlier with Code 28, missing driver installation is
a plausible explanation. An unlit LED alone does not establish a defective adapter or scanner.

## 2026-09-06 21:40 EDT / 2026-09-07 01:40 UTC — requested probe retry

Repeated Windows inventory before attempting the authorized single-status exchange.
`Keyspan USA-19H ` remains present as USB VID06CD/PID0121, with status Error,
ConfigManagerErrorCode 28, and no driver service. No Keyspan COM port is assigned.
COM3 and COM4 remain Bluetooth serial ports and were not opened.

No Keyspan/USA-19H application entry was found in the standard HKLM 64-bit, HKLM 32-bit,
or HKCU uninstall registry locations. This is evidence that the downloaded MSI has not
registered an installation there; it is not an exhaustive Windows Driver Store audit.
The extracted MSI exists and is 2,492,416 bytes. Installation is the outstanding next step.

Result: no serial handle opened, TX 0 bytes, RX 0 bytes, TX/RX hex empty, no response CRC
or scanner fields available. No configuration, baud change, reset, or continuous scanning
command was sent. The retry stopped at preflight because there is no verified Keyspan COM
port to probe. The downloaded driver's release notes require detaching its USB connection
before running the MSI and reconnecting after installation; keep Memory Integrity enabled.

## 2026-09-06 21:45 EDT — native Windows driver installed

The user explicitly authorized installing the native Windows driver and disconnected the
USB cable. Present-device enumeration found no Keyspan before installation. Rechecked the
downloaded ZIP hash against the value recorded above, then ran its MSI with administrator
rights, automatic restart disabled, and verbose logging.

Installation returned **exit code 0**. The MSI log reports `Keyspan USA19H Driver` installation
completed successfully; log: `tmp/keyspan-install-20260906-214512.log`.

Windows Driver Store enumeration after installation reports:

| Driver | Published INF on this PC | Version/date | Signer |
| --- | --- | --- | --- |
| USB, `19h.inf`, provider KSPN | `oem74.inf` | 17.14.44.557 / 2024-08-16 | Microsoft Windows Hardware Compatibility Publisher |
| Ports, `19hp.inf`, provider KSPN | `oem79.inf` | 17.14.44.551 / 2024-08-16 | Microsoft Windows Hardware Compatibility Publisher |

Both packages report Declarative and Attested attributes. These driver-package signatures
are separate from the unsigned installer wrappers previously reported. OEM numbers are
observations on this PC, not portable identifiers or uninstall instructions.

Docker verification: existing Linux container is healthy; pyserial 3.5 and the project's
TCP transport/native bridge modules import successfully. A Windows USB driver cannot be
installed into that Linux container. The native Windows bridge remains the supported path
from a host Keyspan COM port to Docker. No container was connected to physical hardware.

The user was asked to reconnect USB so the actual port binding and the authorized single
9600-baud status exchange can be verified. Installation alone is not a successful scanner probe.

Post-install `Win32_DeviceGuard` verification still reports Memory Integrity running
(`SecurityServicesRunning=[2,7]`, VBS status 2); security settings were preserved.

## 2026-09-06 21:49 EDT / 2026-09-07 01:49 UTC — first physical status request

The user confirmed USB reconnection. Native Windows serial enumeration identified
`Keyspan USB Serial Port (COM7)`, manufacturer `Keyspan`, hardware ID
`KEYSPAN\*USA19HMAP\00_00`. The virtual port's USB VID/PID fields are null; its USB parent
was identified earlier as the user-confirmed USA-19HS. No Bluetooth port was used.

Ran the bounded native command:

```powershell
.\.venv\Scripts\python.exe -m lms200.cli probe-status --port COM7 --log docs\diagnostics\probe-COM7-20260907T014847Z.jsonl
```

| Item | Physical result |
| --- | --- |
| Settings | RS-232, fixed 9600 baud, 8 data bits, no parity, 1 stop bit; flow control disabled |
| Port opened | **Yes** |
| Stale input | Cleared before transmission |
| Request count | **One** |
| Host-driver-accepted TX | **7 bytes** |
| Raw TX hex | `02 00 01 00 31 15 12` |
| Request address / command / payload length | `00` broadcast / `31` status / 1 byte |
| Request CRC | Computed and appended word `1215`; wire bytes `15 12` |
| RX bytes / hex | **0 bytes**, empty hex string |
| ACK / NAK | Neither received |
| Response framing / CRC | No response available to validate |
| Device type / firmware / active baud / units / mode / geometry / status flags | Unavailable: scanner did not reply |
| Outcome | Timeout before ACK, using the configured 250 ms ACK deadline with USB margin |
| Port closed | **Yes**, in cleanup; no LMS stop telegram sent |

The CLI exited 1 to signal an unsuccessful probe. Its raw event transcript is
[probe-COM7-20260907T014847Z.jsonl](diagnostics/probe-COM7-20260907T014847Z.jsonl).
Zero CRC errors means no frame was received, not that a scanner CRC was verified.
TX count reports acceptance by the Windows driver, not oscilloscope confirmation of signals.

The former missing-driver/no-COM blocker is resolved, and COM7 was available to open.
This test does not establish why the scanner is silent: scanner power/startup, the RS-232
cable crossover, ground, interface selection, or an existing different scanner baud may
still require checking. The request matches the documented independent golden vector.
No further status attempt was made, including at 19200/38400; current authorization is
limited to the single 9600 request. No configuration, password, reset, or continuous-output
command was sent. Wiring changes require the external 24 V supply switched off.

## 2026-09-06 21:54 EDT / 2026-09-07 01:54 UTC — status request after idle LED report

The user reported that the Keyspan green LED is slowly flashing and supplied a native
Windows status-test procedure. Re-enumeration again identified `Keyspan USB Serial Port
(COM7)` with hardware ID `KEYSPAN\*USA19HMAP\00_00`. Bluetooth COM3/COM4 were not opened.
The existing hardware confirmations and RS-232-only restrictions remain in effect.

Ran one fresh bounded native `probe-status` attempt at fixed 9600 8-N-1 with all flow
control disabled. COM7 opened successfully; the Windows driver accepted exactly seven
TX bytes: `02 00 01 00 31 15 12`. Independently recomputed request CRC `1215` matches the
appended little-endian bytes `15 12`. RX was zero bytes (empty hex), with no ACK, NAK,
or complete frame. No response CRC could be validated. The attempt timed out and closed
the port successfully. No configuration, baud change, continuous scan, or stop was sent.

This used the existing probe's 250 ms ACK deadline, followed by a three-second response
window only if ACK arrives; it did not use the pasted example's unconditional three-second
read. No further attempt or scanner power cycle was performed. The slow adapter LED
indicates an idle port, but does not establish scanner readiness or RS-232 cable continuity.
The LMS200 scanner's own LED state is still awaiting an operator report.

Raw transcript: [probe-COM7-20260907T015455871Z.jsonl](diagnostics/probe-COM7-20260907T015455871Z.jsonl).

## 2026-09-06 21:57 EDT / 2026-09-07 01:57 UTC — green scanner LED, three-second listen

The user reported a green LED on the LMS200 and explicitly requested another receive test.
Native Windows enumeration again identified the Keyspan as COM7. Extended only the bounded
diagnostic probe's pre-ACK receive window from 250 ms to 3 s so a quiet port is observed for
the full three seconds. The first ACK, if received, starts a 3 s response deadline. This
host-side diagnostic change does not alter scanner settings or normal service timeouts.
The report now records both timeout policies and elapsed listening time.

Before opening hardware, all 16 status-probe tests passed, including new synthetic tests
for a delayed ACK and a full silent receive window with one transmission and port closure.
Targeted Ruff formatting/lint passed; mypy passed across 23 source files.

Physical result: COM7 opened at RS-232 9600 8-N-1, with flow control disabled. The Windows
driver accepted one request, seven bytes: `02 00 01 00 31 15 12` (request CRC `1215`, wire
`15 12`). Measured listening time was **3.0 s**. RX was **0 bytes**, hex empty, no ACK/NAK,
no response frame, and therefore no response CRC or scanner status fields to validate.
The probe timed out, exited 1, and closed COM7 successfully. No additional telegram,
scanner setting change, baud search, stop, power cycle, or continuous scan occurred.

The green LED is an operator observation, not a successful serial protocol exchange.
The longer receive window did not resolve the silence. Physical serial wiring/crossover,
ground, and the scanner's existing serial settings remain unverified by a response.

Raw transcript: [probe-COM7-20260907T015746517Z.jsonl](diagnostics/probe-COM7-20260907T015746517Z.jsonl).

## 2026-09-06 22:11 EDT / 2026-09-07 02:11 UTC — diagnostic tool and passive listener

Read the user's attached staged diagnostic request and all accessible supplied manufacturer
manuals. The two old Eaton product/support URLs failed; their current manufacturer product
page supplied equivalent support resources. Visually checked corrected SICK pinout, Keyspan
DB9 pinout and the startup/status example. The full source audit, verified observations,
remaining hypotheses and physical confirmation boundaries are in `HARDWARE_DIAGNOSTIC.md`.

Native CIM/PnP query at 02:01 UTC confirmed COM7 and its USB parent VID06CD/PID0121.
Both signed KSPN drivers report OK and device error 0. No matching serial application was
listed then. A successful exclusive open, rather than process listing alone, establishes
availability. The audit found that previous `probe-status` writes returned seven bytes but
did not call `flush()`; the earlier tool also cleared received input before listening.

Installed the new `lms200-hardware-diagnostic` console command with ports, listen-startup,
status and guarded loopback. It journals all raw bytes, frame boundaries/CRCs, initial state,
write/flush results and exceptions. No scanner configuration command is available. New tests
exercise passive capture, noisy/fragmented bytes, the published startup CRC, delayed data,
stuck flushing, exact isolated loopback, refusal without isolation consent, and port closure.
Full native suite: 92 passed, 2 skipped; formatting, Ruff and mypy pass.

At **02:11:00 UTC**, the passive listener opened COM7 exclusively at 9600 8-N-1 with all
flow control disabled, DTR false and RTS false. Initial driver readings: CTS false, DSR true,
RI false, CD true, input/output queues both zero. These are driver-reported control states,
not a continuity measurement. Since hardware flow control is disabled, CTS does not gate TX.

The listener announced readiness and transmitted **zero bytes**. The user was asked to confirm
readiness before physically cycling only the scanner's normal 24 V supply, leaving the data
and USB links connected. It continues reading while awaiting confirmation, with a bounded
five-minute preparation window. No status request or loopback has been run in this stage.
Append-only raw journal: [hardware-raw.jsonl](diagnostics/hardware-raw.jsonl), listener run ID
`580817ca-3af2-44ea-9806-9cc5fe2a4e84`. A follow-up entry will record completion/closure.

## 2026-09-06 22:14 EDT / 2026-09-07 02:14 UTC — staged physical capture completed

The user explicitly confirmed readiness to power-cycle, then confirmed **Power restored**.
Only after that reply was the fresh `tmp/lms200-power-restored-20260907T0211Z` marker created.
The already-running listener recorded that confirmation at **02:13:26.150870 UTC** and
continued its zero-TX capture for 65 seconds.

At 02:14:14.096-02:14:14.107 UTC, Windows delivered seven individual received bytes:

```text
TX: (empty; 0 bytes)
RX: 10 04 21 00 28 01 A0
```

There is no `02` STX, no standalone ACK `06` or NAK `15`, and no complete telegram. No
response CRC can be computed/validated for this input. The parser recorded seven noise
bytes, while preserving every byte in the raw journal. The source cannot be identified
as a valid LMS200 startup message; receiving these bytes alone does not verify the cable.
The listener timed out at **02:14:31.169760 UTC**, 65 seconds after confirmation, and closed
COM7. Total open listening time including operator preparation was **210.922 s**. No OS
exception occurred. This is a completed but unsuccessful startup-telegram capture.

After closure, ran the one authorized native status command at **02:14:39 UTC**:

```text
TX attempt:           02 00 01 00 31 15 12
write() return:       7
TX accepted by driver: 02 00 01 00 31 15 12
Request CRC:          1215 (wire 15 12), valid
flush():              completed
Output queue:         0
Post-flush listening:  3.031 seconds
RX:                   (empty; 0 bytes)
ACK / NAK:            neither
Response CRC:         unavailable; no frame
OS exception:         none
COM7 closed:          yes
```

Status run ID `a3fc50df-efd6-4488-aeec-ec2b0cb5d05d`; the result was logged at
02:14:42.320045 UTC. `write()` plus `flush()` demonstrate driver acceptance and queue
drainage; they do not directly measure voltage transitions at the DB9 pins. No valid reply
or loopback currently proves end-to-end transmission of those seven bytes.

No additional probe, baud change, configuration, software reset, continuous scan or loopback
was sent. The remaining likely layer is the physical serial path or its settings; the
adapter/cable/scanner interface cannot yet be isolated. Further progress requires the user
to power off and disconnect the scanner cable from the Keyspan, then separately confirm the
safe adapter-only 2-3 loopback preparation. **Stop condition 5** applies; no jumper or cable
inspection is authorized by the completed power-cycle confirmation alone.

## 2026-09-06 22:18 EDT / 2026-09-07 02:18 UTC — requested repeat with separate power steps

The user requested another passive/startup/status sequence because they were unsure that
the previous power disconnection occurred at the intended time, and asked whether the bytes
were hexadecimal. The supplied image is a manual page, not authorization for its configuration
or streaming flowchart. Existing 9600/RS-232/read-only limits remain in effect; no loopback.

Offline inspection confirmed `STATUS_REQUEST` has Python type `bytes`, length 7, hex
`02 00 01 00 31 15 12`, integer values `[2, 0, 1, 0, 49, 21, 18]`, and a valid CRC. It is
passed directly to `write()`, not ASCII-encoded hex text. RX logging also uses hexadecimal
display of the received binary bytes. The screenshot's full 29-byte startup example has
payload length 23 and valid CRC `5A64` (wire `64 5A`), and the framer accepts it offline.
No serial port was opened by those verification checks.

Re-enumeration identified Keyspan COM7. At **02:18:56.612526 UTC**, the new passive listener
opened COM7 at fixed 9600 8-N-1 with all flow control disabled, DTR/RTS false and initially
empty input/output queues. It announced readiness with TX 0. The user was asked first to
switch only the normal LMS200 24 V supply off, confirm that scanner LEDs are off, and leave
it off until the next instruction. USB and data links remain connected throughout.

Listener run ID `8bc94614-04ef-46bd-8e68-c76c69dfe9bb`, append-only `hardware-raw.jsonl`.
The fresh power-restoration marker will be created only after explicit operator confirmation;
the code is unchanged from the tested diagnostic. A follow-up entry will record outcomes.

## 2026-09-06 22:22 EDT / 2026-09-07 02:22 UTC — repeat with confirmed OFF then ON

The operator replied **Power off; scanner LEDs off**. Before directing power back on,
confirmed the original passive listener was still running at 02:20:18 UTC. The operator
then replied **Power is ON now**, after the instruction to restore only the normal 24 V
supply and leave USB/data connections intact. No physical change was performed by software.

The listener opened at 02:18:56.612526 UTC and recorded:

| Time UTC | Event |
| --- | --- |
| 02:20:53.862810 | RX `00`, before the power-on reply was recorded |
| 02:21:08.558079 | Explicit operator power-on confirmation marker observed; 65 s capture window started |
| 02:21:23.611676-02:21:23.616743 | RX `39 14 31 21 31 01` |
| 02:22:13.565634 | Timeout; no valid startup frame; COM7 closed |

Total passive listening time including preparation was **196.953 s**. Full TX is empty
(zero bytes); full RX is **`00 39 14 31 21 31 01`**, seven bytes. No `02` STX, ACK or NAK,
no complete telegram, no CRC to validate, and no OS exception. All bytes were preserved;
no receive-buffer clear occurred after opening. This listener was active before both
operator-confirmed power steps, reducing the concern about opening it too late. The bytes
cannot be identified as a valid LMS200 telegram or used to establish a specific fault.

After passive closure, ran one native status request at 02:22:25 UTC. COM7 opened at the
same fixed 9600/8-N-1/no-flow-control settings; DTR/RTS false, input/output queues initially
zero. TX **`02 00 01 00 31 15 12`**, `write()` returned **7**, `flush()` completed and
`out_waiting` was **0**. A **3.015 s** post-flush listen received **zero bytes**, no ACK/NAK
and no response frame/CRC. No OS exception; COM7 closed at 02:22:28.818656 UTC.

Status run ID `9f9fa19d-f2f7-45b4-beac-7af8e0b7eda4`; append-only raw evidence remains in
`docs/diagnostics/hardware-raw.jsonl`. Actual DB9 line signals are still not independently
measured: seven returned by write and an empty output queue establish driver-side progress.
The test did not change scanner settings or start streaming. No loopback, jumper, cable
disconnection or additional retry was performed. Next isolation remains adapter-only
loopback after separate power-off/disconnection and safe 2-3-jumper confirmations.

## Operator confirmed adapter isolation before loopback

The user reports that everything after the Keyspan is disconnected: the black Q.C. adapter
and gray LMS200 data cable are removed, the LMS200 is powered off, and the Keyspan's metal
DB9 pins are exposed. Only the Keyspan remains connected to the computer by USB. The Q.C.
adapter's model/function/pin mapping have not been verified; no assumption is made about it.

Native enumeration still identifies `Keyspan USB Serial Port (COM7)` with hardware ID
`KEYSPAN\*USA19HMAP\00_00`. Enumeration did not open COM7 or transmit any bytes. The
operator has not yet confirmed a safe Keyspan pin 2-3 link. Loopback remains unperformed;
the next required confirmation is that only those two exposed adapter pins are connected
with a suitable jumper while the scanner/cable remain disconnected.
