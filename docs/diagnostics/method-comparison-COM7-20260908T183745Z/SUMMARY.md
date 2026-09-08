# Python, native C++ and ROS 2 comparison — 2026-09-08

**All three selected methods completed without receiving any bytes.** Five status
requests were accepted by the Windows driver (35 bytes total). No ACK, NAK,
complete frame or response CRC was available. The angle/continuous-output stages
were not reached because the native status gate did not pass.

The operator selected the sequential comparison and the gated 100°/1° sequence;
reported the scanner ON and then `green`. The previously confirmed direct
Keyspan→gray cable→LMS200 RS-232 setup was retained. Exact replies and the scope
are in [PLAN.md](PLAN.md). No new LED change, power cycle or wiring change is
inferred from these results.

| Test | Bytes transmitted | Bytes received | ACK or NAK result | Valid frame result | CRC result | Interpretation |
|---|---|---|---|---|---|---|
| Normal Python | 7; one `02 00 01 00 31 15 12`; write returned 7, flush complete/output queue 0 | 0 before TX and during 5.000 s after flush | Neither | None; no length or B1 to validate | Request `1215` valid; response unavailable | No status exchange |
| Direct Win32 C++ | 21; three identical status requests, each completed count 7 and output queue 0 | 0 across one healthy reader; post-drain windows 5.024, 5.023, 5.020 s | Neither | None | All requests valid; response unavailable | Persistent background reader did not establish communication |
| ROS 2 / LaViRIA through Windows | 7; one identical status request; original-library PTY count 7, Windows write 7, flush complete/output queue 0 | 0; Windows 6.110 s after flush, ROS 2 6.032336 s after send | Neither | None | Request valid; response unavailable | No exchange through the selected ROS 2 harness |
| 100°/1° variant, continuous output and stop | 0 | Not attempted | Not applicable | Not applicable | Not applicable | Native status prerequisite failed; these operations were not tested |

Every physical write used seven binary bytes, not ASCII hex. `15 12` is the
little-endian request CRC. With no RX bytes, zero reported CRC failures is not a
response CRC pass. Driver completion counts and empty output queues do not prove
signals reached the scanner connector.

COM7 was native Windows, exclusive, 9600/8-N-1 with flow control off and DTR/RTS
false for each run. Each handle stayed open throughout its own run. Native C++ had
an independent ReadFile worker active during TX and drain. Python and the Windows
ROS 2 wrapper read synchronously, relying on Windows receive buffering during
their short write/flush calls. There was no application RX reset after initial
open; pyserial itself purges during initial open. The native implementation uses
no receive purge. Switching backends necessarily closed and reopened COM7.

Windows timeline (UTC):

* Python opened 18:38:42.756; flush completed 18:38:42.883; closed by final result
  18:38:47.900. PID 12536, run ID `05275ced-9f3e-4ca1-be9d-d9912f162a00`.
* Native opened 18:39:03.701; reader armed 18:39:03.703, before first TX; closed
  18:39:19.018. Reader healthy, no serial query/read failure, no logging failure.
  The pending ReadFile cancellation error 995 at closure is recorded cleanup,
  not a failed receive window. Native `rx.bin` is an empty, preserved capture.
* ROS 2 wrapper opened 18:44:05.422; both readers ready 18:44:10.482; status
  authorized 18:44:10.544; Windows flush completed 18:44:10.618; closed by final
  result 18:44:16.760. PID 41300, run ID `89027525-f7af-407e-b9c3-c0c21b9ee502`.
  The node/relay exited 3, PTY closure was confirmed, and the wrapper exited 1
  for no exchange. No serial exception or relay cleanup error occurred.

Windows and WSL wall clocks differ. Use each process's recorded monotonic receive
duration; do not subtract timestamps across the Windows and ROS 2 journals.
All three host commands reported failure/no exchange. No next run is queued.

The ROS 2 wrapper gained an explicit already-powered-on checklist mode for this
comparison. It records the pre-run confirmation, waits for both readers and
captures pre-TX bytes before authorizing one packet. It does not read or create
power-on/startup acknowledgment files, claim a startup capture, or request another
power cycle. Collected early node TX remains rejected after authorization. The
original OFF/startup/65-second path remains available and tested. Production
Python behavior and the original third-party SDK/DLL/scanning node are unchanged.

Validation before live use: 76 native offline checks; 78 focused Python tests
(22 ROS 2 controller, 56 hardware diagnostic); Ruff format/lint and mypy; 642 ROS 2
C++ self-checks; all 20 ROS build inputs/artifacts and all native manifest hashes
verified. The unchanged real ROS 2 node had passed both 80/81 synthetic PTY
exchanges earlier in this session; those were not new physical results.

Evidence:

* [Python raw journal](python-status.jsonl), [Python input hashes](python-input-hashes.json).
* [Native result](native/result.json), [timestamped native events](native/events.jsonl),
  [native raw bytes](native/rx.bin), [native build manifest](native-build-manifest.json).
* [Windows ROS 2 raw journal](ros2/windows-raw.jsonl),
  [Windows ROS 2 result](ros2/windows-result.json),
  [ROS 2 raw events](ros2/ros2-events.jsonl),
  [ROS console](ros2/ros2-console.log), [ROS build manifest](ros2/build-evidence.json).

This comparison does not identify the failed component. The cable/scanner link
remains unresolved despite the previously passed bare Keyspan loopback. No
configuration, baud, reset, field, laser, stream-start or stop telegram was sent
in this comparison. Original LMSAPI and the unavailable MST package were not
rerun; the operator selected the three methods above.
