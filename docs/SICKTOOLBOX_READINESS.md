# SickToolbox and ROS LMS200 preparation

Prepared 2026-09-07 with the scanner disconnected, as requested. Only source
downloads, static inspection, compilation and local file staging were performed.
No scanner executable, ROS node, serial listener, USB attachment, or hardware
test was started. Upstream communication sources and the project's current
Windows/Python drivers were not changed.

**SickToolbox is present and builds. A ROS 2 LMS200 candidate also builds on the
installed Jazzy environment. These are compiled evaluation artifacts, not yet
qualified for live use with this Keyspan setup.** The legacy ROS 1 wrapper is
downloaded for reference; it cannot run directly in ROS 2 Jazzy.

Follow-up preparation for the user's next session installs the exact LaViRIA
C++ SDK and ROS 2 package persistently under `.local/laviria_lms200`.
[Start with this setup guide and offline check](../tools/sicktoolbox_offline/README.md).
The earlier temporary build/install artifacts and their evidence remain preserved.

## Available sources and builds

All source versions are pinned in
[sources.lock.json](../tools/sicktoolbox_offline/sources.lock.json). Vendor
checkouts, their bundled manuals and generated files stay outside Git and Docker
build contexts. Source licenses remain in the downloaded checkouts.

| Component | Local source | Result |
|---|---|---|
| [ROS drivers SickToolbox](https://github.com/ros-drivers/sicktoolbox/tree/9ad2fbf962e7ac46991ced5ce81a6536895bed6c), package 1.0.104 | `third_party/sicktoolbox` | Built `libSickLMS2xx.a` and eight original LMS2xx examples using GNU 13.3/C++14 in WSL Ubuntu 24.04. Headers, library and BSD license staged under `tmp/sicktoolbox-build/install`. |
| [sicktoolbox_wrapper](https://github.com/ros-drivers/sicktoolbox_wrapper/tree/32bd9d5c823567471cd22b6cfe84436768a45680), 2.5.4 | `third_party/sicktoolbox_wrapper` | Downloaded and inspected. Requires ROS 1 catkin/roscpp; not built or installed into Jazzy. Its defaults include 38400 baud and `/dev/lms200`. |
| [LaViRIA ROS 2 LMS200 node](https://github.com/LaViRIA/sick_lms200_node/tree/0a8f7f0362bd0373b71f709003f36bace7e7cd54) | `third_party/sick_lms200_node` | Built unchanged with installed ROS 2 Jazzy/GNU 13.3/C++17; current executable under `.local/laviria_lms200/lib/sick_lms200_node/sick_lms200_node`. Important live-use defects below. |
| [LaViRIA legacy SickToolbox dependency](https://github.com/LaViRIA/sicktoolbox/tree/2b486d2b3b1299f4401f04c2193f244b594fb532) | `third_party/sicktoolbox-1.0.1` | Built into the ROS 2 candidate and as standalone `.local/laviria_lms200/lib/libSickLMS.a` with headers/CMake import. It uses `SickLMS`, while the ROS drivers fork uses `SickLMS2xx`; these directories/API generations are not interchangeable. |

The standalone examples are `lms2xx_simple_app`, `lms2xx_config`,
`lms2xx_mean_values`, `lms2xx_partial_scan`, `lms2xx_real_time_indices`,
`lms2xx_set_variant`, `lms2xx_stream_range_and_reflect`, and `lms2xx_subrange`.
Compilation does not imply every example applies to LMS200: the reflectivity
overload is intended for LMS-FAST variants. The simple application is the relevant
continuous-range example. No examples were executed, including help commands.

The libraries retain original BSD license files. The ROS 2 node's package metadata
declares BSD, but its checkout lacks a separate license/copyright file; clarify
the exact license terms before redistributing that node.

## What the C++ API actually does

The ROS drivers library explicitly lists model `SICK_LMS_TYPE_200_30106` in
[`SickLMS2xx.hh`](../third_party/sicktoolbox/include/sicktoolbox/SickLMS2xx.hh).
Its standard `GetSickScan(values, count)` overload enters continuous range mode
on the first call (`20 24`) and receives B0 scans on subsequent calls.
`Uninitialize()` requests `20 25` to stop streaming, then requests the default
9600 baud. The original simple example captures ten scans, not ten seconds.
It has no bounded capture deadline or explicit Ctrl+C stop handler.

`Initialize(9600)` itself sends a baud-setting command before reading status.
On timeout it searches other rates, including 500000, then requests mode 25 and
reads model/status/configuration. Specifying 9600 is therefore **not** a guarantee
of fixed-9600-only traffic. The ROS 2 candidate's dependency has similar behavior.
Neither is an equivalent replacement for the existing minimal raw-status test.

## Findings requiring review before a live experiment

Line references below refer to the pinned, unchanged local sources.

| Severity | Source/function | Verified behavior and consequence |
|---|---|---|
| High | ROS drivers `SickLMS2xxBufferMonitor.cc:46,85`; LaViRIA `SickLMSBufferMonitor.cc:46,85` | Payload buffer is 812 bytes, but the check permits the total message limit of 818. Lengths 813–818 can overrun the local payload buffer before CRC validation. Reject lengths exceeding the actual payload buffer before reading. |
| High | ROS drivers `SickLMS2xx.cc:128–150`; LaViRIA `SickLMS.cc:127–145`, `Initialize` | Initial baud writes, retries and fallback search can exceed the present RS-232/9600 experimental scope. A fixed-baud profile must disable search, including the 500k path; a launch parameter alone does not do so. |
| High | ROS 2 `src/sick_lms200_node.cpp:155–166` | Start/stop services only log messages. Stop explicitly leaves scanning active. They are not usable controls for the requested start/capture/stop sequence. |
| Medium | Both buffer monitors' header search at `:59` | Accept only `02 80`; discard `02 81`. Standalone ACK/NAK bytes are skipped during the search. A missing parsed frame does not establish zero received bytes. |
| Medium | ROS drivers `SickBufferMonitor.hh:337`, `SickLMS2xxBufferMonitor.cc:112` | Per-byte timeouts can discard an incomplete local frame; no complete raw TX/RX evidence stream is exposed by these examples. |
| Medium | ROS drivers `SickLMS2xx.cc:2396,2746,2754` | Baud changes use `TCSAFLUSH` and `TCIOFLUSH`, which can discard queued data. Reader `tcdrain` is an output wait, not that purge. |
| Medium | ROS 2 node `:128–135` | Divides all ranges by 1000 without checking scanner measuring units. Centimetre data would be scaled incorrectly. Invalid/overflow measurement codes are also published as ordinary ranges. |
| Medium | ROS 2 node `:55,86,118` | Uses a fixed 75 Hz timer/scan-time claim. At 9600 8-N-1, even a 100°/1° scan's roughly 212-byte telegram takes about 0.221 seconds on the wire; this link cannot deliver 75 complete scans per second. Motor rate and delivered scan rate must be distinguished. |
| Medium | ROS 2 node `:39–42,94–103` | Connects immediately on construction; error cleanup does not delete the object after failed initialization, or if uninitialization throws. No guarded passive start or bounded capture exists. |
| Medium | LaViRIA `SickLMS.cc:2317`, `_setupConnection` | Opens with `O_RDWR | O_NOCTTY`, without `O_NDELAY`. This differs from the newer ROS drivers fork, which already has `O_NDELAY` at `SickLMS2xx.cc:2334`. Review carrier-wait behavior and subsequent read flags before adopting this older backend. This is not evidence about the previous Windows error 5. |

The standard LMS2xx serialization path does not use inappropriate `htons()` or
`ntohs()` conversions or write a C++ struct directly. In the ROS drivers fork,
`SickLMS2xxMessage.cc:85–92` copies explicitly converted length and CRC fields into
a byte array. `SickLMS2xxUtility.hh` keeps them little-endian on this x86 build.
`WORDS_BIGENDIAN` must remain undefined on x86: defining it as zero would still
select that file's swapping branch. Linux/WSL/Docker does not independently change
the telegram byte order. This static check is not a fresh wire-vector test.

These observations do not identify the root cause of the earlier missing Windows
RX. Neither of the newly downloaded libraries generated those historical captures.

## Windows / WSL readiness

Ubuntu 24.04 and ROS 2 Jazzy were already installed. The standalone SDK was built
with a separate CMake project to avoid adding ROS 1/catkin to that environment.
The Windows `usbipd` executable is also installed. No USB device was bound or
attached during preparation.

The running WSL kernel is `6.18.33.2-microsoft-standard-WSL2`. Its `/proc/config.gz`
reports `CONFIG_USBIP_VHCI_HCD=m` but **`CONFIG_USB_SERIAL_KEYSPAN` is not set**.
Therefore this kernel was not built with the Keyspan serial driver. Merely
attaching the USB adapter is insufficient to qualify this WSL serial path.
An exploratory module search also encountered permission denial in `lost+found`;
it is not evidence of a successful or exhaustive external-module check.
The [Linux Keyspan configuration](https://github.com/torvalds/linux/blob/master/drivers/usb/serial/Kconfig)
and [driver source](https://github.com/torvalds/linux/blob/master/drivers/usb/serial/keyspan.c)
identify the relevant driver. No kernel/module/firmware installation or host
configuration change was made.

The Windows COM7 name is not a POSIX tty path. These Linux binaries cannot open
COM7 directly, and the Windows Keyspan driver is not a Linux driver. A future
Linux path needs compatible Keyspan kernel support and verified USB attachment,
or a separately reviewed serial bridge integration. SickToolbox assumes tty
baud/control ioctls, so substituting a TCP URL is not sufficient.
[Microsoft's USB attachment documentation](https://learn.microsoft.com/en-us/windows/wsl/connect-usb)
also states that a device attached to WSL is unavailable to Windows during that
attachment. Keep exactly one selected owner. Nothing here changes the existing
native Windows diagnostic or proves that changing operating systems will fix RX.

## Rebuild without running a driver

From the repository in PowerShell, these commands only compile and stage files:

```powershell
wsl.exe -d Ubuntu-24.04 -- bash /mnt/c/Users/Jeffr/OneDrive/Documents/GitHub/Gepruft_Lidar/tools/sicktoolbox_offline/build-wsl.sh
wsl.exe -d Ubuntu-24.04 -- bash /mnt/c/Users/Jeffr/OneDrive/Documents/GitHub/Gepruft_Lidar/tools/sicktoolbox_offline/build-ros2-wsl.sh
```

Both scripts check source commits and tracked changes. The ROS 2 script uses the
existing `/opt/ros/jazzy`, with local install staging rather than a system install.
Build logs are `tmp/sicktoolbox-build.log` and `tmp/ros2-lms200-build.log`.
Recorded artifact hashes and build results are in
[build-evidence.json](../tools/sicktoolbox_offline/build-evidence.json).
Compiler warnings from the legacy source are preserved. No live smoke test was
performed. The review parameter template
[ros2-review-parameters.yaml](../tools/sicktoolbox_offline/ros2-review-parameters.yaml)
uses an intentionally nonexistent device path and desired baud 9600. It is not a
launch file and does not override hidden library behavior.

For a later authorized ROS session, this direct ament installation exposes
`.local/laviria_lms200/share/sick_lms200_node/local_setup.bash`, not a
top-level `install/setup.bash`. Source the installed base Jazzy environment first.
The installed executable's hash differs from its build-tree copy because CMake
removes its build RPATH during installation.

## Smallest remaining preparation before live use

1. Choose a supported serial host path. The existing native Windows diagnostic
   remains available; WSL Keyspan support is a separate unresolved prerequisite
   for these particular Linux binaries.
2. In a separate reviewed patch, fix the payload bounds, preserve raw bytes before
   parsing, accept the intended response addresses, and add a fixed-9600 profile
   with no baud search or ambiguous configuration retries. Keep the original
   pinned source for comparison.
3. If ROS 2 is needed, implement real start/stop and bounded capture, reliable
   cleanup, units/invalid-range conversion, and delivered-scan timing. The current
   ROS 2 candidate is not suitable unchanged for that sequence.
4. Verify those changes offline with malformed/fragmented frames, both addresses,
   fixed-baud command traces, units, and stop/shutdown behavior. Only after that
   should a separately authorized connected test progress from raw status to
   continuous output. No test is queued or scheduled.

The first future hardware test should still establish a raw, CRC-valid status
reply before starting streaming. Switching to a library that suppresses raw
traffic would otherwise make the existing no-RX investigation less observable.

## 2026-09-08 follow-up — selected Windows-bridge ROS 2 diagnostic

The operator selected a separate, guarded ROS 2 status test through the working
Windows Keyspan driver. The WSL Keyspan kernel setting remains absent; original
LaViRIA source/install hashes still match. `tools/ros2_status` adds a ROS 2 harness
using original library serializer/CRC/send components with project-owned persistent
framing and anonymous-pipe/PTY integration. It does not qualify or patch the
unchanged upstream scanning node described above.

The supervised direct-Keyspan test completed after separate OFF/ON/startup
confirmations and 65 s of startup listening. Passive RX was zero; one seven-byte
status request was accepted/flushed by Windows, with zero RX in 6.718 s, no ACK,
NAK or valid frame. Both readers closed and no scanning followed. See
[the run summary](diagnostics/ros2-status-COM7-20260908T182110Z/SUMMARY.md) and
[the bridge test guide](../tools/ros2_status/README.md). Communication remains unresolved.
