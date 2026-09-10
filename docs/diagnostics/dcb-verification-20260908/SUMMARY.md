# Fresh COM7 DCB verification — 2026-09-08

**Confirmed for the Python hardware diagnostic, native Windows C++ diagnostic,
and Windows serial owner used by the guarded ROS 2 diagnostic.** Each independently
opened COM7 exclusively, successfully configured it, called `GetCommState` on that
same handle after configuration and immediately before its sole status write,
and closed the handle before the next program opened it. No required setting
mismatch or serial configuration/readback API failure occurred in these runs.

The operator reported that the adapter's pins 2–3 loopback had passed, then
confirmed startup complete/green and restoration of the scanner cable, removal
of the loopback link, and closure of other COM7 applications. That current report
supersedes the earlier pending-loopback state; no additional loopback or physical
change was performed. Authorization was one status request per program.

## Actual driver readbacks

All timestamps below are **Windows UTC on 2026-09-08**. Handles are process-local;
the same value within each row belongs to that program's two readbacks and write.
The programs do not share a handle across processes.

| Program / verdict | After configuration | Immediately before TX | Same handle | Windows accepted TX | RX and post-drain duration | Closed |
|---|---|---|---|---|---|---|
| Python hardware diagnostic — **confirmed** | 19:38:35.508174 | 19:38:35.626546 | `0x218`, PID 45236 | 7 bytes, one write; flush complete, queue 0 | 0 bytes / 5.015 s | 19:38:40.659983 |
| Native C++ — **confirmed** | 19:39:19.668 | 19:39:19.882 | `268` = `0x10C` | 7 bytes, one WriteFile; drain complete, queue 0 | 0 bytes / 5.023 s | 19:39:24.920 |
| ROS 2 Windows serial owner — **confirmed** | 19:44:16.417803 | 19:44:21.301757 | `0x348`, PID 41696 | 7 bytes, one write; flush complete, queue 0 | 0 bytes / 6.500 s | 19:44:27.841973 |

All six readbacks report:

```text
BaudRate = 9600
ByteSize = 8
Parity   = 0 = NOPARITY
StopBits = 0 = ONESTOPBIT = one stop bit
fParity  = 0 (parity checking disabled)
fBinary  = 1
```

`StopBits` is a Windows **enum**, not a literal number of framing bits.
`ONESTOPBIT=0`, `ONE5STOPBITS=1`, and `TWOSTOPBITS=2`. Symbols are resolved against
the installed pyserial Windows definitions or native Windows SDK constants.
See Microsoft's [DCB definition](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-dcb).

Hardware flow control is **off**: `fOutxCtsFlow=0`, `fOutxDsrFlow=0`,
`fDsrSensitivity=0`, `fDtrControl=0=DTR_CONTROL_DISABLE`, and
`fRtsControl=0=RTS_CONTROL_DISABLE`. DTR and RTS are disabled static outputs in
these three diagnostics. CTS/DSR input levels are separate observations and do
not themselves enable flow control.

Software flow control is **off**: `fOutX=0` and `fInX=0`. Native C++ reports
`fTXContinueOnXoff=1`; the two pyserial owners report `0`. That field governs
continuation following receive-buffer XOFF behavior; it does not enable XON/XOFF
when both software-flow flags are zero. `fNull`, `fErrorChar`, and
`fAbortOnError` are also zero in every readback.

The Python and ROS 2 records separately label `pyserial_cached_settings` (requested
library properties: baudrate 9600, bytesize 8, parity `N`, stopbits 1, xonxoff/rtscts/
dsrdtr false) and `windows_dcb` (actual `GetCommState` result). Cached properties
alone are not the basis for these verdicts. Their `confirmed:true` values have
empty mismatch dictionaries and refer to actual Windows results.

Python's older top-level `host_baud_confirmed:false` records that no nondefault
host-baud trial was authorized; it is not the DCB verdict. Likewise, its
startup/power-cycle fields belong to the separate passive-startup modes, which
were not used in this single-status run. Current readiness came from the
operator's replies above. The actual configuration verdict uses the two explicit
`dcb_after_configuration` / `dcb_pre_tx` readbacks.

## Source paths and later changes

Paths below are relative to the repository root
`C:\Users\Jeffr\OneDrive\Documents\GitHub\Gepruft_Lidar`.

| Path | Open/configure/readback/write behavior | Later configuration path |
|---|---|---|
| [`src/lms200/hardware_diagnostic.py`](../../../src/lms200/hardware_diagnostic.py) | `run_diagnostic`: closed `serial.Serial(port=None, **serial_config)`, assign COM7/DTR/RTS, `open()`; shared readback after open and before `device.write(request)`. `run_status_repeat` has its own open and the same checks before every attempt. | Baud is selected before open, default 9600; nondefault CLI rate requires a separate explicit opt-in. Neither function changes settings after open. Status/capture/startup/direct-test/loopback use the common run path; only one status mode was run here. Repeat mode was inspected, not run. |
| [`tools/lms200_native/win_serial.cpp`](../../../tools/lms200_native/win_serial.cpp) | `WinSerial::open`: exclusive `CreateFileW(L"\\\\.\\COM7", ..., share=0, ..., FILE_FLAG_OVERLAPPED, ...)`, explicitly assign DCB 9600/8/NOPARITY/ONESTOPBIT/fParity false and flow flags, checked `SetCommState`, checked `SetCommTimeouts`, checked actual DCB/timeouts. `verify_settings_json` repeats actual same-handle readback; `WinSerial::write` invokes it directly before `WriteFile`. | One `SetCommState` in open, none afterward. Reader/queue/modem queries do not reconfigure framing. [`main.cpp`](../../../tools/lms200_native/main.cpp) uses new `--status-only` to call `exchange(Status)` once, bypassing the broader sequence and all retry/start/stop stages. |
| [`src/lms200/ros2_status_experiment.py`](../../../src/lms200/ros2_status_experiment.py) | Actual native Windows COM7 owner: closed pyserial object, explicit COM7/DTR/RTS, open, shared DCB readback. `SingleStatusGate` accepts exactly one status packet from the WSL relay, then a second DCB readback precedes `device.write(packet)`. | No subsequent baud, framing, or control-line setter. It never calls the SDK's broader scanner Initialize sequence. |
| [`src/lms200/windows_serial_state.py`](../../../src/lms200/windows_serial_state.py) | New shared helper initializes `DCBlength`, calls `serial.win32.GetCommState(device._port_handle, byref(actual))`, resolves enum names, logs requested/actual separately and rejects unavailable or mismatched native Windows settings before TX. | Opens no handle and calls no configuration API. |

The installed dependency `.venv/Lib/site-packages/serial/serialwin32.py` was also
inspected. `open` uses Windows `CreateFile` with share mode zero. `_reconfigure_port`
assigns `BaudRate`, `ByteSize`, `NOPARITY` plus `fParity=0`, `ONESTOPBIT`, and flow
control flags, and checks `SetCommState`. Property setters can reconfigure an
already open object, but none is used after configuration in these three runs.
Its initial internal `GetCommState` return is not checked by pyserial; the new
independent checked readback therefore supplies evidence beyond the dependency's
requested properties. The installed dependency was not edited.

ROS 2's [`tools/ros2_status/src/status_node.cpp`](../../../tools/ros2_status/src/status_node.cpp)
and [`pty_relay.py`](../../../tools/ros2_status/pty_relay.py) use a WSL PTY and pipes.
PTY termios settings are not COM7's DCB. The Windows owner above is the source of
physical-port configuration evidence. The unchanged general LaViRIA scanning
node was not launched.

Other repository paths were inspected and **are not yet verified by a fresh
COM7 run in this audit**:

- General [`src/lms200/bridge.py`](../../../src/lms200/bridge.py) uses
  [`transports/serial.py`](../../../src/lms200/transports/serial.py), a different
  owner from the guarded ROS 2 experiment. It opens `serial_for_url` at explicit
  8/N/1/no flow and defaults to 9600. Static DTR/RTS use pyserial defaults, which
  are asserted, distinct from handshake modes. Its data channel forwards bytes
  unchanged. Its separate control channel can explicitly call `set_baud`; the
  production state machine also has explicit host-baud changes during configured
  initialization. These are real later-setting paths, absent from the focused
  runs. The shared transport now verifies after open, before writes, and after
  explicit host-baud changes against the selected baud. No general bridge server
  or production initialization was launched here.
- Legacy [`src/lms200/status_probe.py`](../../../src/lms200/status_probe.py)
  separately opens pyserial at 9600/8/N/1/no flow with DTR/RTS false. It has no later
  framing setter, but no added DCB readback and its older RX-reset/no-flush behavior
  remain; it is not the Python diagnostic used above.
- [`src/lms200/reset_experiment.py`](../../../src/lms200/reset_experiment.py)
  separately opens using `SERIAL_CONFIG`, DTR/RTS false, with no later framing
  setter. It remains unexecuted and lacks a fresh readback. Reset is outside this
  status-only authorization.
- The original-DLL [`lmsapi_experiment.py`](../../../src/lms200/lmsapi_experiment.py)
  dispatches a separate x86 helper with COM7/9600 arguments. Those arguments do
  not establish its DLL-owned handle's current DCB. No DLL connect was run; its
  configuration-on-connect experiment is outside these three diagnostics.

## Exact transmitted data and outcome

Every run supplied the same seven binary bytes:

```text
02 00 01 00 31 15 12
```

Python uses a `bytes` buffer and pyserial's Windows `WriteFile(handle, data,
len(data), ...)`. Native C++ uses its byte vector's `data()` and explicit byte
count. ROS 2 builds the original-library message, relays its exact bytes, and
the Windows gate writes a `bytes` buffer. Hex conversion is for logs/pipe encoding
and is reversed before the physical write. No ASCII hex, newline, or manually
inserted start/stop bits is supplied to COM7. The `02` is a protocol STX **byte**;
it is not a manually inserted UART start bit. With 8-N-1 configured, the adapter
handles start and stop framing automatically.

All three driver writes completed with count 7 and output queue zero. All
received zero bytes, with no ACK, NAK, or valid telegram. Python exited 1, native
C++ 3, and the ROS 2 Windows owner 1 / WSL node 3 because status communication
was not established; these codes are not DCB failures. Native `may_retry:true`
describes the exchange result, but `--status-only` never executes a retry.
The native reader remained healthy. All ports/relay processes closed. No run is
queued and no scanner configuration, baud change, reset, or scan command was sent.

ROS 2's own post-send duration was 6.012571 s. Windows/WSL UTC clocks differ; use
each process's monotonic durations rather than subtracting timestamps across OSes.

[GetCommState](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getcommstate)
verifies **what the Windows driver reports on the open handle**. It does not
establish that the scanner received the request, demonstrate connector voltages
or on-wire timing, or replace an oscilloscope/serial signal measurement. Neither
zero RX nor the passing driver configuration identifies a scanner/cable fault.

## Evidence and validation

- [Python timestamped raw/DCB/write/result log](python.jsonl), [raw RX file](python.rx.bin).
- [Native timestamped event log](native/events.jsonl), [result](native/result.json),
  [raw RX](native/rx.bin), [matching source/executable manifest](native/build-manifest.json).
- [ROS 2 Windows timestamped raw/DCB/write/result log](ros2/windows-raw.jsonl),
  [Windows result](ros2/windows-result.json), [ROS 2 events](ros2/ros2-events.jsonl),
  [28-entry matching build manifest](ros2/build-evidence.json).
- [Offline saved-evidence checker](verify_evidence.py) verifies all six DCB
  records, exact one-write counts, closed-before-next-open ordering, and the
  archived native/ROS 2 source and artifact hashes. It passed after the live runs
  and never opens a serial port. Run it from the repository root with
  `.\.venv\Scripts\python.exe docs/diagnostics/dcb-verification-20260908/verify_evidence.py`.

Offline validation before live execution: 213 Python tests passed, 2 skipped;
Ruff format/lint and mypy passed; 90 native checks passed (36 protocol, 25
sequence, 29 serial observations); 642 ROS 2 C++ checks passed. Both rebuilt
ROS 2 synthetic PTY exchanges (addresses 80 and 81, fragmented startup/status)
passed without opening COM7. Native source/executable and ROS 2 manifest hashes
matched before their runs. Native executable SHA256:
`F9A474817528A06791F5C17C2466E8F888790CB26E55680ED612B66357955950`.

Negative tests cover an unavailable readback, Windows error 5, and mismatched
DCB fields; diagnostic transmission is blocked and the handle is closed. No
deliberate bad-configuration trial was performed on hardware. No 8-N-1 mistake
was found to correct; the missing evidence was addressed with checked logging
and pre-write gates. A WSL build failed on CRLF before any hardware access;
the four invoked project shell scripts were normalized to LF and assigned
explicit Git line-ending rules. The successful build followed that correction.

The exact live commands already executed, sequentially from repository-root
native Windows PowerShell outside the restricted execution sandbox, were:

```powershell
.\.venv\Scripts\python.exe -m lms200.hardware_diagnostic status --port COM7 --baud 9600 --timeout 5 --confirm-scanner-interface --log docs/diagnostics/dcb-verification-20260908/python.jsonl --raw-rx docs/diagnostics/dcb-verification-20260908/python.rx.bin
.\tmp\native-lms200\lms200-native.exe --run --confirm-hardware --status-only --output docs/diagnostics/dcb-verification-20260908/native
.\.venv\Scripts\python.exe -m lms200.ros2_status_experiment --run --confirm-powered-on-direct-checklist --log-dir docs/diagnostics/dcb-verification-20260908/ros2
```

These are records of completed runs, not queued commands. Any later authorized
run must use fresh evidence paths and current applicable operator confirmations.
