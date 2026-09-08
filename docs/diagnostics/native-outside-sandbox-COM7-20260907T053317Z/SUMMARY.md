# Native rerun outside the execution sandbox

2026-09-07 05:33:17–05:33:32 UTC. The user requested fixing the access-denied
failure, keeping the reader open, and rerunning the bounded sequence. Prior current
hardware confirmations and the selected optional 100-degree/1-degree flag were
retained. The user's Keyspan blinking observation was logged as an operator report.

This comparison used the **same executable** as the earlier 05:24 run: SHA256
`948FDF106BBC11DB6CB5C6AF7FAC2A688FC865DBA09C3862137A9D523792401E`.
All source/build-input hashes matched the manifest immediately before execution.
It ran directly in PowerShell outside the restricted agent execution environment.
The original binary is retained under `tmp/native-lms200/archive/<SHA256>`.

- COM7 opened exclusively with 9600/8-N-1 and the same explicit DCB/timeouts.
- One reader armed before TX and stayed active until normal shutdown, about 15 s.
- Three exact status telegrams `02 00 01 00 31 15 12` were attempted. Each Windows
  completion reported seven bytes; all three output queues drained to zero.
- Post-drain listening windows were 5027, 5042, and 5003 ms.
- OS-delivered RX, saved raw bytes, ACK/NAK, CRC-valid frames, and CRC failures
  were all zero. `rx.bin` is empty. No candidate frame reached CRC validation.
- No `ClearCommError` failure or other reader failure occurred. The final
  cancellation error 995 is the expected aborted pending read during shutdown,
  recorded with an unavailable completion count; it is not an acquisition fault.
- Status was never confirmed, so no variant, start, ten-second streaming capture,
  or stop command was sent. The program closed COM7 and exited 3.

The access-denied symptom did not recur outside the sandbox. This supports an
execution-context explanation, with transient driver conditions still possible.
The cause is not proven by one comparison. It separately demonstrates a healthy
software reader with zero reported RX during complete status reply windows.
Driver-accepted TX counts do not establish physical serial signals or scanner
receipt; this result does not identify a scanner, adapter, cable, or interface fault.

The byte-order audit found explicitly little-endian lengths, numeric fields, and
CRCs in the native/Python paths, unchanged byte-buffer forwarding, and no network
order conversion or direct struct transmission. Docker itself introduces no
telegram byte swapping. Detailed findings are in `tools/lms200_native/README.md`.

Preserved artifacts: `rx.bin`, `events.jsonl`, `result.json`, `console.log`, and
`build-manifest.json`. The initial sandbox failure remains in its separate
`native-COM7-20260907T052445Z` directory.
