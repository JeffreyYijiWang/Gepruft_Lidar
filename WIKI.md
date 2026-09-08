# Gepruft Lidar project wiki

Progress record for the SICK LMS200-30106, part 1015850. Last updated September 8,
2026, from the repository's saved code, manifests, raw captures and results.
This is a local wiki-style project document. [README](README.md) provides the
short status overview and application setup.

## Current outcome

The project has a Python acquisition application, simulator, recording/replay and
dashboard, plus several independently prepared diagnostic paths. The exact LaViRIA
SickToolbox and ROS 2 packages are installed locally. A guarded ROS 2 diagnostic
has also completed physical status tests through the Windows Keyspan driver.

**No validated scanner status reply or real scan data has been established in the
reviewed physical trials.** The latest completed comparison returned zero incoming
bytes in Python, native C++, and guarded ROS 2. All three closed their physical
port handles. The cause of missing replies is still unknown.

The test logs contain successful port opens and driver-reported writes. Those are
useful milestones, but they do not measure electrical transmission at the scanner.
No streaming milestone is marked complete merely because a program built, a
simulator worked, or an adapter LED blinked.

## Equipment and experiment scope

| Item | Recorded setup |
|---|---|
| Scanner | SICK LMS200-30106, legacy LMS2xx binary telegram protocol |
| Host | Windows, with Ubuntu 24.04 / ROS 2 Jazzy in WSL |
| Adapter | Keyspan USA-19HS; Windows observed it as COM7 |
| Serial profile used in recent trials | RS-232, 9600 baud, 8 data bits, no parity, one stop bit; flow control off |
| Recent connection | Operator-confirmed direct Keyspan → gray cable → LMS200; black adapter absent |
| Setup evidence | Operator confirmations establish reported fit, open scanner pins 7–8, no jumpers and completed startup; they are not cable-continuity or electrical measurements |

COM7 is an observed assignment, not a permanent device identity. A future test
must establish the current port and physical state. The power/data connector
details and corrected wiring references remain in the
[hardware guide](docs/HARDWARE.md); this progress record does not prescribe rewiring.

## Software paths and what actually ran

| Path | Role and execution history |
|---|---|
| Python application | Pure protocol code, one asynchronous device service, serial/TCP/simulator/replay transports, CLI/API, recording and dashboard. Simulator demonstrations exercise this software path. |
| Python hardware diagnostic | Native Windows pyserial owner with raw capture and bounded status requests. Several physical trials completed. |
| Native C++ diagnostic | Direct Win32 `CreateFile`/overlapped read/write path in `tools/lms200_native`. One receive worker remains active through status attempts. Its optional variant/stream sequence requires successful earlier exchanges. |
| Original LMSAPI 1.1c | Original 32-bit DLL in a separate Windows helper. One authorized configuration-on-connect experiment failed to connect; active raw traffic is hidden by that DLL. |
| Original LaViRIA packages | Pinned, compiled and installed for offline use. The unchanged scanning node has not been used as the physical status-test implementation. |
| Guarded ROS 2 status diagnostic | Project-owned ROS 2 node using original LaViRIA message/CRC and send components. A Windows controller owns COM7; pipes and a WSL pseudo-terminal carry bytes to/from ROS 2. It sends one allowed status packet and bypasses original initialization/baud search. |
| SICK MST Demo research | Documentation was located; the original demo distribution was not located during the recorded search. No MST executable was run. |

The ROS 2 physical status path is:

```text
ROS 2 diagnostic + LaViRIA message/send code
    ↕ Linux pseudo-terminal and anonymous pipes
Windows controller + native Windows serial driver
    ↕ COM7 / Keyspan / RS-232 cable
LMS200
```

The three recent methods share the same adapter, cable, scanner and Windows
driver. They compare software paths; they are not three independent electrical
measurements. The ROS bridge also shares Windows pyserial with the Python path.
See [architecture](docs/ARCHITECTURE.md), [native C++](tools/lms200_native/README.md)
and [guarded ROS 2](tools/ros2_status/README.md).

## Development and investigation timeline

Dates below use UTC for recorded hardware events. Events shortly after midnight
UTC on September 7 occurred on September 6 in America/New_York (EDT).

| Date / time | Progress or experiment | Recorded result |
|---|---|---|
| September 6, local | Initial application, protocol, simulator, dashboard, recording and replay | The [implementation report](docs/IMPLEMENTATION_REPORT.md) records offline tests and a simulator recording/replay demonstration. These are historical software results, not physical LMS200 scans. |
| September 6, local | Windows Keyspan driver setup | [Driver inspection](docs/diagnostics/windows-keyspan-20260907T020132Z.json) records COM7 and driver/device status. Windows enumeration does not establish scanner communication. |
| September 7, 01:48–02:22 UTC | Initial status and passive startup experiments | Status attempts returned no validated replies. Passive captures saved short binary sequences without a complete telegram. [Initial log](docs/HARDWARE_DIAGNOSTIC_LOG.md), [raw journal](docs/diagnostics/hardware-raw.jsonl). |
| September 7, before 03:03 UTC | Adapter isolation and loopback | The operator reported a successful bare-Keyspan loopback. A separate older isolator-path capture failed; those are distinct observations. See the evidence distinction below. |
| September 7, 03:03–03:08 UTC | Direct connection with black adapter bypassed | Passive RX `F0 39 14 31 21 31 01`; subsequent status RX 0 over 5 s. No valid startup/status frame. [Raw result](docs/diagnostics/direct-COM7-20260907T030336Z.jsonl). |
| September 7, before original-DLL trial | LMSAPI CRC comparison | Two published vectors and 522 synthetic inputs agreed with the project CRC. [Saved offline result](docs/diagnostics/lmsapi-offline-20260907.json). |
| September 7, 03:57–03:59 UTC | Original LMSAPI DLL experiment | Passive RX contained seven unclassified bytes. Original connect returned null after configuration-entry failure. Active raw TX/RX, standalone ACK and wire CRC were unavailable. [Raw transcript](docs/diagnostics/lmsapi-original-COM7-20260907035741Z.jsonl). |
| September 7, 04:07–04:08 UTC | Ten bounded Python status requests | Ten writes of 7 bytes, each followed by at least 5 s of reception; RX 0, no ACK/NAK/frame. [Raw result](docs/diagnostics/status-repeat-COM7-20260907040746Z.jsonl). |
| September 7, 04:21 UTC | Retaining incomplete frames across empty reads | One further status test still recorded RX 0 over 5.016 s. The parser improvement did not create a hardware reply. [Raw result](docs/diagnostics/status-fragment-preserve-COM7-20260907042133Z.jsonl). |
| September 7, 05:24 UTC | First native C++ live run | One status write; receive window ended after 563 ms with `ClearCommError` error 5. It was a shortened capture, not a full timeout. [Result](docs/diagnostics/native-COM7-20260907T052445Z/result.json). |
| September 7, 05:33 UTC | Same native binary outside the restricted sandbox | Three complete status windows without the earlier access denial; RX 0. [Summary](docs/diagnostics/native-outside-sandbox-COM7-20260907T053317Z/SUMMARY.md). |
| September 7, 05:43 UTC | Corrected native diagnostic-query handling | Healthy reader, three status writes, full 5.024/5.024/5.010 s windows, RX 0. [Result](docs/diagnostics/native-reader-fix-COM7-20260907T054336Z/result.json). |
| September 7 | SickToolbox and ROS preparation | Exact LaViRIA SDK/node builds installed locally; hashes, headers and ROS package registration checked. [Install evidence](tools/sicktoolbox_offline/laviria-install-evidence.json). |
| September 8, 18:21–18:23 UTC | Guarded ROS 2 status after confirmed startup | Readers ready before power-on; status sent after separate confirmations and 65.016 s. Windows recorded RX 0 over 6.718 s after flush. [Summary and evidence](docs/diagnostics/ros2-status-COM7-20260908T182110Z/SUMMARY.md). |
| September 8, from 18:38 UTC | Sequential Python / native C++ / ROS 2 comparison | All methods completed with RX 0; no validated status, no variant or streaming. Details below. |

The historical hardware log contains intermediate entries such as “loopback
pending.” Later results supersede those descriptions of what remained to do;
they are preserved as part of the chronology.

## Latest completed comparison

The [comparison plan](docs/diagnostics/method-comparison-COM7-20260908T183745Z/PLAN.md)
selected sequential tests with the scanner already powered on. Each method
retained its own handle during its test and closed it before the next method
opened. No single physical handle was shared across all three backends.

All requests were binary `02 00 01 00 31 15 12`. CRC `1215` is represented on the
wire as `15 12`; the text shown here is the hexadecimal rendering of seven bytes.

| Evidence | Python | Native C++ | Guarded ROS 2 through Windows |
|---|---|---|---|
| Status writes | 1 | 3 | 1 |
| OS-reported TX | 7 bytes | 21 bytes | 7 bytes at Windows |
| Output flush/drain | Completed, queue 0 | Queue 0 after each write | Completed, queue 0 |
| Reply window | 5.000 s after flush | 5.024 / 5.023 / 5.020 s after drain | Windows 6.110 s after flush; ROS 2 6.032336 s after send |
| Incoming bytes | 0 | 0; saved `rx.bin` also empty | 0 at both readers |
| ACK / NAK | Neither | Neither | Neither |
| Complete / CRC-valid response | None | None | None |
| Confirmed real scan data | None | None | None |
| Serial error | None recorded | Reader healthy at close | None recorded by Windows |
| Physical port closed | Yes | Yes | Yes |

Evidence: [Python events/result](docs/diagnostics/method-comparison-COM7-20260908T183745Z/python-status.jsonl),
[native result](docs/diagnostics/method-comparison-COM7-20260908T183745Z/native/result.json),
[native events](docs/diagnostics/method-comparison-COM7-20260908T183745Z/native/events.jsonl),
[ROS Windows result](docs/diagnostics/method-comparison-COM7-20260908T183745Z/ros2/windows-result.json),
[ROS events](docs/diagnostics/method-comparison-COM7-20260908T183745Z/ros2/ros2-events.jsonl).

The native program's requested 100°/1° change, start, ten-second capture and stop
were **not attempted**: the prerequisite status exchange failed. The expected
Win32 cancellation code 995 during final reader cancellation is separate from a
receive-worker failure. The earlier error 5 did not recur in this comparison.

Windows and WSL wall clocks had an observed offset in the ROS trials. The windows
above use each process's own elapsed timer, not subtraction across those clocks.

## What the evidence establishes

Port opening, write acceptance, incoming bytes, a frame, and a valid scan are
separate milestones:

| Milestone | State in this project |
|---|---|
| Open the selected port and apply serial settings | Demonstrated by multiple completed native Windows trials |
| OS accepts the intended status bytes | Demonstrated in the instrumented Python/C++/guarded ROS paths |
| Receive some bytes from a connected setup | Demonstrated in earlier passive captures; the bytes remain unclassified |
| Receive scanner ACK/NAK or a complete valid response | Not established in the reviewed instrumented physical trials |
| Retrieve semantically valid real scan data | Not established |

Earlier passive samples include `10 04 21 00 28 01 A0`, `00 39 14 31 21 31 01`,
`F0 39 14 31 21 31 01` and `C0 39 14 31 21 31 01`. None forms a complete scanner
telegram in these captures. They are binary data rendered as hex, not proof of
ASCII/binary confusion. Their source and cause have not been established.

The successful bare-Keyspan loopback is an **operator-reported result** recorded
in the [hardware diagnostic notes](docs/HARDWARE_DIAGNOSTIC.md). A successful bare
loopback raw transcript was not located during this documentation review.
[isolator-loopback-raw.jsonl](docs/diagnostics/isolator-loopback-raw.jsonl) records
a separate failed experiment and must not be cited as proof of the reported pass.
This evidence distinction does not erase the operator's later confirmation.

Original LMSAPI hides its active serial traffic. Its missing active byte counts
remain unavailable, not zero. Likewise, a green scanner LED, a blinking Keyspan,
or a driver write result does not establish a valid scanner response.

## Fixes and findings retained

The diagnostic work improved observability and control: raw bytes are logged
before parsing, incomplete frames survive empty reads in the guarded captures,
reply windows are bounded and measured, and status results gate later operations.
Native C++ distinguishes optional `ClearCommError`/modem-query failures from actual
read failures and represents unavailable observations explicitly.

The original native error 5 disappeared when the same binary was run outside the
restricted sandbox. That supports an execution-context explanation, but its exact
permission mechanism remains unproven. It does not explain the later complete
windows with zero incoming bytes.

The [byte-order/open-flags review](docs/NATIVE_OPEN_FLAGS_AUDIT.md) found no missing
POSIX `O_NDELAY` flag in the active Win32 path; Win32 uses different APIs.
The [SickToolbox source review](docs/SICKTOOLBOX_READINESS.md) distinguishes the
newer ROS drivers fork, which already uses `O_NDELAY`, from the older LaViRIA
dependency, which does not. No inappropriate network-order conversion or direct
struct-to-serial write was established in the reviewed active native/Python paths.
Running Linux or Docker does not itself swap the telegram's bytes.

The unchanged LaViRIA library/node still have documented receive bounds/address
limitations, automatic baud fallback, and a ROS stop service that does not stop
scanning. Those limitations matter before adopting the original scanning node.
The guarded ROS status tool bypasses that initialization/monitoring path; its
empty raw captures cannot be attributed to rejecting bytes it never received.

## Imported packages and offline verification

| Package | Pinned revision |
|---|---|
| LaViRIA SickToolbox | `2b486d2b3b1299f4401f04c2193f244b594fb532` |
| LaViRIA ROS 2 LMS200 node | `0a8f7f0362bd0373b71f709003f36bace7e7cd54` |

The installation under `.local/laviria_lms200` includes `libSickLMS.a`, nine SDK
headers, CMake import `LaViRIA::SickLMS`, and the original ROS package. The
[package guide](tools/sicktoolbox_offline/README.md) provides an offline check and
environment setup. Source checkouts and generated artifacts are local/ignored;
they must be fetched and rebuilt after cloning onto another computer.

Recorded validation milestones include the LMSAPI CRC comparison, 76 native C++
self-checks, and the ROS diagnostic's 642 C++ checks, 68 focused Python tests and
two synthetic PTY exchanges. These counts describe specific recorded revisions
and scopes, not a claim that today's entire repository test suite has passed.
The [ROS test summary](docs/diagnostics/ros2-status-COM7-20260908T182110Z/SUMMARY.md)
also documents the full-suite limitation. No tests or hardware runs were started
to write this page.

Direct USB access from the recorded WSL kernel lacks built-in Keyspan support
(`CONFIG_USB_SERIAL_KEYSPAN` unset). The guarded Windows bridge avoids that
dependency; it does not repair or qualify direct WSL access. No kernel change is
required merely to read these documents or verify the saved package metadata.

## Remaining work

1. Establish one raw, CRC-valid and semantically valid status response, including
   the expected acknowledgment, before attempting continuous acquisition.
2. Choose an evidence-producing next test for the shared serial path. Cable
   crossover/continuity, signal ground, scanner interface selection, retained
   baud/configuration and scanner-side interface faults remain possibilities;
   none is established as the root cause. Physical work requires its own current
   setup confirmation.
3. Preserve raw TX/RX and elapsed windows independently of parsing. Classify a
   future result as zero bytes, unclassified/partial data, invalid frames or a
   valid reply; keep original bytes in every case.
4. Review and verify the original LaViRIA scanning implementation's known defects
   before enabling it. Keep its imported version and comparison evidence intact.
5. After status and configuration readback succeed, validate the requested
   geometry, confirmed continuous start, bounded scan capture and confirmed stop.

The completed experiments do not authorize an automatic rerun. No new hardware
test, rewiring, scanner-setting change or publication was performed for this
documentation update.

## Keeping this record current

After a meaningful change or completed trial, update the README's current outcome
and append a timeline entry here. Keep historical evidence files intact. A plan
or permission to try a stage is not evidence that the stage ran successfully.

Use this entry format:

```text
Date/time and timezone:
Objective and method:
Code revision / source and executable hashes:
Hardware state and operator confirmations, if applicable:
Change made:
Offline checks actually run and their scope:
Raw TX attempted / OS-reported write / output drain:
Raw RX bytes and capture duration:
ACK/NAK / complete frame / CRC / semantic result:
Actual scan count and whether start/stop were confirmed:
Errors, closure, and evidence paths:
Conclusion, remaining uncertainty, and smallest next step:
```

The [reference index](docs/references/README.md) points to the manufacturer manuals
and recorded discrepancies. Link to those sources rather than redistributing the
PDFs. This wiki and the README remain local repository files until explicitly
published.
