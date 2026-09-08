# Native C++ run: status stage aborted

Run: 2026-09-07 05:24:45–05:24:46 UTC (01:24 EDT), directly from PowerShell.
Executable: `tmp/native-lms200/lms200-native.exe`, x64 native Win32; its SHA256
and ten build-input hashes matched the archived `build-manifest.json` immediately
before execution. All 34 protocol and 25 sequence/handshake offline checks passed.

The operator freshly confirmed scanner powered ON, completed startup, other COM7
applications closed, and selected the optional 100-degree/1-degree change.
No wiring or LED-change observation was requested or inferred.

| Stage/evidence | Observed result |
|---|---|
| Open and serial setup | Succeeded. Exclusive COM7; effective 9600/8-N-1, all hardware/software flow control disabled, DTR/RTS disabled, DSR sensitivity off. |
| Persistent reader | Armed before TX; 200 ms passive interval; zero reported pre-TX bytes. |
| Status TX intent | One binary request: `02 00 01 00 31 15 12`. |
| Windows write completion | `GetOverlappedResult` reported 7 bytes, error 0, complete. This is not physical-transmission proof. |
| Output drain | Output queue reported zero; no RX/TX purge. |
| Receive window | Aborted after 563 ms following drain, instead of the planned 5 s, because `ClearCommError` failed with Win32 error 5. |
| Raw RX | OS-received 0; binary-saved 0; decoder-fed 0. `rx.bin` is empty. These counts cover the completed observation interval only. |
| ACK/NAK/frames | None reported. CRC-valid frame count 0 and CRC-failure count 0 mean there was no candidate frame to validate. |
| Optional angle change | Not attempted; status gate failed first. |
| Continuous start/capture/stop | Not attempted. This program had not attempted start, so cleanup stop was unnecessary. |
| Exit | COM7 closed, process exited 3. No additional native run or automatic retry was performed. |

The direct failure was in Windows serial-status observation, not an observed
scanner rejection or parser rejection. Microsoft defines error 5 as
[ERROR_ACCESS_DENIED](https://learn.microsoft.com/en-us/windows/win32/debug/system-error-codes--0-499-).
[ClearCommError](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-clearcommerror)
returns communications error/queue status and reports API failure through
GetLastError; this is separate from the UART-error flags it returns on success.
The successful observations logged UART error mask 0. Error flags during and
after the failed call are unavailable.

The cause of that API denial remains unknown. This run does not establish silence
through a complete reply deadline, physical transmission, or an adapter/scanner
fault. It does demonstrate that this native reader reported no incoming bytes
before its failure; the parser did not reject a received reply in that interval.

A subsequent read-only Windows inspection initially encountered access denial
inside the execution sandbox. Repeating only that inspection outside the sandbox
succeeded: PnP listed Keyspan COM7 as OK and no matching native/Python/LMSAPI process
was present. `Win32_SerialPort` did not enumerate Keyspan, so it supplies no Keyspan
health evidence. These later observations do not identify why the earlier serial
API failed or prove which environment component caused it. The inspection opened
no serial handle and transmitted nothing. See `windows-inspection.json`.

The next narrowly scoped investigation is execution-permission/driver behavior
at `ClearCommError`, preserving the same binary and settings. A separate bounded
status-only comparison outside the restricted execution environment could test
that explanation; it has not been queued or run. No wiring or scanner-setting
change is justified by this result alone.

Artifacts: `rx.bin`, `events.jsonl` (13 parsed records), `result.json`, `console.log`,
`build-manifest.json`, `windows-inspection.json`. The event log remains the original
output; this summary adds interpretation without altering it.
