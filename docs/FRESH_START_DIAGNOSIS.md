# Fresh investigation: SICK LMS200-30106 / Keyspan USA-19HS

Collected 2026-09-08, about 19:00-19:20 UTC, directly on the Windows host.
Earlier conversations and diagnostic conclusions were not used as proof. The
current reported connection is USB-C connection -> Keyspan -> serial cable -> LMS
data interface. No additional serial converter or isolator is assumed. The supplied
attachment contains the request text, not the referenced photograph/manual image.

**Driver update: unnecessary based on current evidence. Scanner communication:
not yet demonstrated in this investigation.** No COM7 handle, driver installer,
scanner command, or power cycle was executed during this investigation.

## Newly observed Windows evidence

[Native inventory](diagnostics/fresh-start-20260908/windows-inventory.json) records
Windows 11 Home **25H2, 10.0.26200.9278, AMD64/x64**. Initial sandboxed CIM queries
returned access denied; the successful queries ran natively outside the sandbox.
That inventory error was not a serial error.

| Component | Freshly observed identity / driver |
| --- | --- |
| Serial port | Keyspan USB Serial Port (COM7), `KEYSPAN\*USA19HMAP\00_00` |
| Serial hardware ID | `KEYSPAN\*USA19HMAP` |
| Serial driver | KSPN, **17.14.44.551**, **08/16/2024**, `oem79.inf` (original `19hp.inf`), service USA19HP |
| USB adapter | Keyspan USB Serial Adapter, `USB\VID_06CD&PID_0121\6&2C1F58E1&0&1` |
| USB hardware IDs | `USB\VID_06CD&PID_0121&REV_0100`, `USB\VID_06CD&PID_0121` |
| USB driver | KSPN, **17.14.44.557**, **08/16/2024**, `oem74.inf` (original `19h.inf`), service USA19H |
| Device status | Both OK, ConfigManagerErrorCode **0** |
| Signature | Both reported signed by Microsoft Windows Hardware Compatibility Publisher |

The PnP parent of the COM7 device is the USB adapter instance above, establishing
the association rather than relying on the COM number alone. `Win32_SerialPort`
listed only Bluetooth ports, so that class alone would have missed this Keyspan.
The CIM date is serialized as August 15 at 20:00 EDT; both installed INF files
explicitly specify **August 16, 2024**. These describe the same UTC date metadata.

The [Eaton support page](https://www.eaton.com/us/en-us/skuPage.USA-19HS.html)
lists a Windows 10/11 driver. The applicable
[official ZIP](https://assets.tripplite.com/drivers/usa-19hs_win11_win10_driver.zip)
was freshly downloaded and its MSI database opened in read-only mode. Its embedded
CAB was extracted without running installer actions. The package's AMD64 INF
entries match this host architecture and hardware IDs. Its release notes dated
December 6, 2024 explicitly address compatibility with Windows Memory Integrity.
Windows 11 is covered; these notes do not separately certify this particular 25H2
build. Keep security settings enabled.

[SHA-256 comparison](diagnostics/fresh-start-20260908/driver-comparison.json) shows
that **both installed INF files and both installed SYS binaries are byte-for-byte
identical to the official package**. ZIP SHA-256:
`B66BB71957994FCDEDC432A8625DCE0BA22408BB16C62A485D69FEA6FCD0BC05`.
The MSI product version is `1.0.0`; the directory dates and the Keyspan manual's
`v3.4` label are not driver versions. There is no newer driver in the inspected
package to install. This does not prove the adapter's physical TX/RX operation.

Reproduce the inventory from a native Windows PowerShell prompt in this repository:

```powershell
.\scripts\inspect-keyspan.ps1 -OutputPath .\docs\diagnostics\keyspan-inventory-new.json
```

Use a new output filename. In Device Manager, expand **Ports (COM & LPT)**, open
Keyspan USB Serial Port (COM7), and record **General / Device status**, **Driver /
Provider, Date, Version**, and **Details / Hardware Ids, Inf name, Parent**. Follow
the parent under USB devices and collect the same fields. This is inspection only.
PnP status does not determine whether another process owns COM7. Close Serial
Assistant, terminals, bridges and any other serial client before a test; the
diagnostic's exclusive Windows open then tests availability at that instant.
An open error may indicate occupancy, permissions or a driver issue; it does not
identify which. Never terminate an unidentified owner automatically.

## Physical interface: documented facts and outstanding inspection

I rendered and inspected page 19 of SICK's
[Technical Description, June 2000](https://www.cs.cmu.edu/~dhuber/files/cmu_laser_sick_docs.pdf).
It explicitly covers LMS200/LMS291; the document also names LMS200-30106. Figure
8-3 is the **power** plug. Figure 8-4 is the **data interface** plug, and Figure
8-5 shows its convertible construction. The two connectors must not be confused:
in particular, data pin 3 is TX, while power pin 3 supplies 24 V. Never connect
power to the Keyspan or serial data pins.

The data table agrees with SICK's
[2008 correction, p3](https://www.sick.com/media/docs/3/33/933/technical_information_lms200_211_221_291_laser_measurement_systems_en_im0027933.pdf).
The specified data plug selects RS-422 with pins 7-8 connected; removing that
bridge selects RS-232. The bridge belongs only inside that plug module. A caption
showing a prepared RS-422 cable does not reveal the state of the user's cable.
Software cannot remove the physical bridge.

For RS-232, the required end-to-end mapping is:

| Sensor DATA contact | Keyspan/PC contact |
| --- | --- |
| 3 TxD | 2 RxD |
| 2 RxD | 3 TxD |
| 5 signal ground | 5 signal ground |

**Actual mapping, cable model, plug-module identity, and bridge state remain
unknown.** With scanner power off and the cable disconnected at both ends, use
the molded pin numbers to record continuity for these three paths and inspect
the specified plug module for a 7-8 bridge. Record unexpected connections too;
never continuity-test a powered circuit. A focused photo of both cable ends,
labels and the data plug module would establish applicability and orientation.
If it is sealed or pin identification is uncertain, stop at the photo/part-number
step. Do not buy or add a null-modem adapter before measuring the existing mapping:
the cable may already provide the crossover.

## Staged tests and exact commands

The existing Python 3.12 environment has pyserial and the editable project. From
another checkout, install with `python -m pip install -e '.[dev]'`. Commands below
run from this repository's root. Choose fresh evidence filenames each time.
Confirmation switches certify physical observations, not a way to skip them.

**1. Fresh isolated Keyspan loopback.** This request explicitly asks for a fresh
test; no historical loopback result is counted. Turn the scanner off and remove
its serial cable completely from the Keyspan. Leave only the Keyspan's USB host
connection. At the adapter's own exposed **male DB9 mating face**, viewed straight
at the pins with the five-pin/wide row above, the top row reads `1 2 3 4 5` from
left to right; below is `6 7 8 9`. A female mating face is mirrored; solder-side
views are also reversed. Use the molded numbers if the connector is rotated.

Link only the Keyspan's pins **2 and 3**, preferably with a correctly numbered
female loopback plug. Confirm scanner off, scanner cable disconnected, USB-only
Keyspan, its 2-3 link fitted, and all other COM7 apps closed before running:

```powershell
.\.venv\Scripts\python.exe -m lms200.hardware_diagnostic loopback --port COM7 --baud 9600 --timeout 3 --confirm-isolated-loopback --log .\docs\diagnostics\fresh-loopback.jsonl --raw-rx .\docs\diagnostics\fresh-loopback.rx.bin
```

The [Keyspan manual, p29](https://assets.tripplite.com/owners-manual/284-20100526164315.933022_a.pdf)
documents pin 2 RX, pin 3 TX and their loopback connection. Serial Assistant's full
external test uses additional handshake links; this program checks the data path
with all flow control off, so it uses **only 2-3**. Do not apply the scanner's
7-8 interface-selection instruction to the Keyspan's RTS/CTS contacts.

One binary pattern is sent: `55 AA 00 FF 11 13 06 15 02 7E 80 01 FE A5 5A`.
Passing requires exactly those 15 returned bytes, without missing, changed, or
extra bytes over the capture window. A pass establishes the host USB/driver and
adapter TX/RX round trip at 9600 under that load. It says nothing about the scanner
or removed cable. A failure leaves the loopback contact, adapter, USB path,
settings and driver operation to distinguish; it does not implicate the scanner.

**2. Verified cable, passive capture.** After the first program closes, remove
the loopback link with scanner power still off. Complete the cable/plug inspection
above, then reconnect only the verified RS-232 data path. Confirm normal fit,
power on, startup complete, no loopback link, and other COM7 apps closed. Then:

```powershell
.\.venv\Scripts\python.exe -m lms200.hardware_diagnostic capture --port COM7 --baud 9600 --timeout 10 --confirm-scanner-interface --log .\docs\diagnostics\fresh-passive.jsonl --raw-rx .\docs\diagnostics\fresh-passive.rx.bin
```

This sends no bytes. Silence is compatible with continuous output being disabled.
It also cannot recover a startup telegram sent before opening the port. If a
startup test becomes necessary, use the existing `listen-startup` workflow with
the listener ready before an explicitly confirmed power cycle; retain its 65-second
post-confirmation bound. No automatic reset or power cycle is part of this plan.

**3. One status request.** After reviewing the passive result and confirming the
same verified, powered and ready setup:

```powershell
.\.venv\Scripts\python.exe -m lms200.hardware_diagnostic status --port COM7 --baud 9600 --timeout 5 --confirm-scanner-interface --log .\docs\diagnostics\fresh-status.jsonl --raw-rx .\docs\diagnostics\fresh-status.rx.bin
```

[SICK's Quick Manual, pp9-10](https://www.danarte.es/archivos/pdf/1866.pdf) supplies
the request and initial 9600/8-N-1/no-flow-control settings. These are a documented
starting hypothesis for this unit, not a measurement of its present baud.
The tool sends exactly seven binary bytes, not ASCII hex or a newline. It captures
before sending, writes once, bounds output flush to one second, then listens for
the full requested five seconds. Write count and flush completion show driver
progress, not independently measured signals at the DB9.

## Packet verification and interpretation

The [Telegram Listing](https://sicktoolbox.sourceforge.net/docs/sick-lms-telegram-listing.pdf),
Table 7-31 p52 and section 9 pp107-108, independently specify the status packet
and checksum. Starting with `02 00 01 00 31`, the checksum states are `0002`,
`0204`, `0409`, `0912`, `1215`. CRC is sent low byte first: **15 12**.
This is SICK's one-shift-per-byte algorithm, not a generic Modbus CRC.
[Offline derivation](diagnostics/fresh-start-20260908/status-crc-verification.json)
matches both the published vector and the project implementation.

The parser validates `total bytes = little-endian payload length + 6`, with an
814-byte limit for the documented indexed-scan extension (Listing p125). Status
decoding supports the two explicit 146/152-data-byte profiles already in the code;
unknown layouts remain raw evidence rather than guessed fields. Each read goes to
the binary file and timestamped hex log before parsing. Empty reads never expire
an incomplete frame; the final report preserves the unfinished suffix. It never
uses line reading or text decoding for transport data. Windows pyserial itself
purges during port open; subsequent diagnostic reads do not reset RX.

| Fresh observation | What it establishes |
| --- | --- |
| RX empty | No bytes delivered in that particular window; not proof of hardware failure |
| Bytes without a valid telegram | Data reached the host; rate, wiring, noise and framing remain hypotheses |
| CRC failure / impossible length / incomplete suffix | Separate counters and original bytes remain available |
| `06` or `15` outside a parsed frame | ACK/NAK-shaped byte; alone, especially amid noise, insufficient proof |
| CRC-valid scanner response | A framed binary response; direction/address and payload are reported separately |
| Post-request ACK plus matching decoded B1, no NAK | Successful status exchange, subject to captured evidence |

Only after loopback and wiring checks, if 9600 yields no valid exchange, consider
separate host-rate trials at **19200**, then **38400**, with the same bounded
capture/status procedure. Each needs explicit authorization and
`--confirm-host-baud-test` with its selected `--baud`; review and stop on any reply
before another trial. The documented retained-baud option means startup need not
restore 9600 (Listing p56). The Keyspan supports these RS-232 rates. This plan
does not send a scanner baud-setting command. No 500000 test is compatible with
this RS-232-only adapter. No automatic rate sweep is scheduled.

The next discriminating measurement is the **fresh isolated adapter loopback**.
If it passes, cable continuity and the data plug's 7-8 state are the next unresolved
physical facts. Present scanner power/startup, port occupancy, actual cable mapping,
interface selection and live baud remain unconfirmed. No successful scanner
communication, electrical silence or particular hardware fault is claimed.

## Offline implementation verification

Final Windows checks: **195 passed, 2 skipped** (hardware opt-in and POSIX-only),
with two dependency deprecation warnings. Ruff formatting/lint and mypy passed;
`git diff --check` found no whitespace errors. Tests exercise fragmented and
delayed frames, corrupted/noisy data, exact and extra-byte loopback, binary-file
persistence before parsing, refusal to overwrite, silence versus valid replies,
host-only baud selection, physical CLI gates, and the existing shared callers.
All serial fixtures in these checks are synthetic; test results are not live
scanner communication. The derived status-request check also ran without serial
imports or hardware I/O.
