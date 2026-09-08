# ROS 2 / LaViRIA status test — 2026-09-08

**Completed: no scanner communication established. COM7 closed; no retry queued.**

The operator selected the guarded ROS 2 status test through Windows. Current WSL
kernel `6.18.33.2-microsoft-standard-WSL2` still lacks `CONFIG_USB_SERIAL_KEYSPAN`;
Windows reported Keyspan COM7 OK and USB bus 5-1 not shared. No USB attachment,
kernel/driver change, Docker execution or physical rewiring was performed.

Operator confirmations: scanner OFF; black adapter removed; Keyspan directly to
the LMS200 RS-232 data port; connectors fit normally; no jumpers/open scanner
data pins 7–8; other COM7 applications closed. After both listeners were ready,
the operator replied `on`, then `green` to the startup-complete confirmation prompt.

## Implementation and verification

This ran a project-owned ROS 2 diagnostic using the pinned original LaViRIA
`SickLMSMessage` serializer/CRC and inherited `SickLMS::_sendMessage` method.
It did not run the unchanged LaViRIA scanning node. A native Windows process
owned COM7, with anonymous pipes and a WSL pseudo-terminal linking the ROS 2
process. The original SDK/source/install remained unchanged.

The Windows gate admitted only one complete `02 00 01 00 31 15 12` packet after
startup confirmation. Neither original `Initialize`/baud fallback nor scan,
configuration, reset or stop methods were called. The two persistent readers
logged raw bytes before parsing and accepted both 80/81 address profiles with
length/CRC checks. There were no received bytes to validate in this physical run.

Offline verification before opening COM7: **642 C++ self-checks passed; 68 Python
diagnostic tests passed; both full PTY/ROS 2 synthetic exchanges passed**, including
600 ms fragment gaps, ACK/B1, both addresses and independently generated CRCs.
Ruff format/lint and mypy for the new Windows controller passed. All 20 recorded
build inputs/artifacts matched their SHA-256 immediately before live execution.
The full project's previously stalled API test suite was not rerun for this test.

* Original LaViRIA SDK commit: `2b486d2b3b1299f4401f04c2193f244b594fb532`.
* Original ROS 2 node commit retained: `0a8f7f0362bd0373b71f709003f36bace7e7cd54`.
* New executable: `.local/ros2_status/lib/lms200_ros2_status/lms200_ros2_status`,
  322,856 bytes; SHA-256 `76c5a5648b2782a054118b198cb03ea72d8b1d660c2567036253481457a292be`.
* New C++ source SHA-256: `caa8d162c5ca1fea7698fa78c897195bc6c02c3dff7bc46115d516b3977d95fe`.
* All input and SDK hashes: [archived manifest](build-evidence.json).

## Physical evidence

Windows UTC times below; WSL records use its own guest clock. Their wall-clock
timestamps have an observed offset, so elapsed capture windows use each process's
monotonic timer and are not computed by subtracting timestamps across hosts.

| Windows UTC | Event |
|---|---|
| 18:21:38.453 | COM7 opened at 9600/8-N-1, flow control off, DTR/RTS false |
| 18:21:43.716 | Both readers ready; zero TX |
| 18:22:31.471 | Explicit power-ON reply recorded |
| 18:23:12.012 | Startup-complete reply recorded (`green`) |
| 18:23:36.486 | Status authorized after 65.016 seconds and startup confirmation |
| 18:23:36.548 | ROS 2 packet received by Windows gate; one binary status write attempted |
| 18:23:36.556 | Windows `write()` returned 7 |
| 18:23:36.559 | Output flush completed; `out_waiting=0` |
| 18:23:43.277 | ROS 2 node exit 3 reported |
| 18:23:43.305 | Final Windows result; COM7 closed |

| Test | Bytes transmitted | Bytes received | ACK/NAK | Valid frame result | CRC result | Interpretation |
|---|---|---|---|---|---|---|
| Passive startup | 0 | 0 in both Windows and ROS 2 logs | Neither | No startup telegram | Unavailable | Startup receive path remains unverified |
| One ROS 2 status request | 7; Windows write 7, flush completed/queue 0 | 0 over 6.718 s after Windows flush | Neither | No B1 or any frame | Request `1215` valid; response unavailable | No communication established |

ROS 2 independently recorded its checked PTY write count of 7 and a 6.010277 s
receive window, zero RX and no valid frame. Windows had no serial API exception;
this was not the earlier shortened error-5 capture. Driver write/flush results
still do not measure electrical transmission at the scanner. No particular cable,
ground, interface setting or scanner fault is established by the empty captures.

The Windows process (PID 37324, run ID `65693b0d-44c8-4c13-a675-b71b9235d52e`)
exited code 1 for no exchange. ROS 2/WSL exited code 3 for no ACK/B1. Both handles
closed, the relay exited, and no next attempt, baud change or scanning was started.
No new LED change was inferred from serial data.

Evidence: [Windows raw/events](windows-raw.jsonl), [Windows result](windows-result.json),
[ROS 2 raw/parser events](ros2-events.jsonl), [ROS 2 console](ros2-console.log).
Historical diagnostic logs are preserved.
