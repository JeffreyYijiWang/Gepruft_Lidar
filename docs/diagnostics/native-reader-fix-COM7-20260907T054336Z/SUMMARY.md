# Corrected native reader: full listening windows, no scanner reply

Run: 2026-09-07 05:43:37–05:43:52 UTC, native Windows PowerShell outside the
restricted execution sandbox. The user's rerun request and prior current hardware
confirmations applied; the optional 100-degree/1-degree selection was retained.

## Changes and offline verification

- `ClearCommError` and `GetCommModemStatus` failures now report independent
  availability/error fields. Unavailable queues, UART flags, and modem inputs are
  null. A failed diagnostic query alone does not terminate the read worker.
- An actual `ReadFile`/completion/wait error is preserved before optional diagnostic
  queries. The previous code could replace that primary error with a secondary
  `ClearCommError` exception; therefore the original shortened run cannot establish
  whether its underlying read operation was still healthy.
- Output drain still requires a successful status query reporting queue zero.
  Failed/unavailable drain does not authorize settings or a status retry. Raw
  receive capture remains active during the bounded wait.
- Added `--listen-only`: a separate ten-second passive capture with no TX. It is
  exclusive with the variant option and closes COM7 at its deadline. Its separate
  CLI path was checked offline; this run used the normal gated command sequence.
- All **76 offline checks passed**: 36 protocol, 25 sequence/handshake, 15 injected
  serial-observation checks. Additional CLI guards rejected passive/settings and
  passive/self-test combinations before any serial open.
- The byte-order audit found no network-order conversion, swapping, or direct
  struct write in the active native/Python/bridge paths. The added reversed-length
  and reversed-B0-count tests reject malformed fields even with recomputed CRC.
- SHA256 of this executable:
  `F89472F0A4177DC2A26E151718E3C057E2CBA6D4A2EB1D8D818CC11397C7B400`.
  Build-input hashes matched immediately before execution. The matching executable,
  source inputs, and manifest are archived under `tmp/native-lms200/archive/<SHA256>`.

## Live evidence

| Evidence/stage | Result |
|---|---|
| Port/settings | One exclusive COM7 handle; effective 9600/8-N-1, flow control/DSR sensitivity off, DTR/RTS disabled. |
| Reader | Armed before TX and healthy at close; no read or diagnostic-query error reported. |
| TX | Three exact `02 00 01 00 31 15 12` status requests. Each Windows completion reported 7 bytes; total 21. |
| Output queue | Each drain confirmed queue zero. No purge or reopen within the run. |
| Reply windows | 5024, 5024, and 5010 ms after the respective drain; reader active throughout. |
| RX | OS-delivered 0, binary-saved 0, decoder-fed 0; `rx.bin` is empty. |
| ACK/NAK/frames | None. No candidate frame was available for CRC validation. |
| Status | Failed: no ACK or complete B1 reply. |
| Optional variant | Not attempted because status failed. |
| Start/capture/stop | Not attempted because status failed. This program did not start streaming, so no cleanup stop was needed. |
| Shutdown | Pending read cancelled intentionally, COM7 closed, process exit 3. Cancellation 995 is expected shutdown evidence, not a receive-worker failure. |

## Interpretation and limits

The reader failure from the initial sandbox run did not recur in either outside-
sandbox run: the unmodified binary at 05:33 UTC and this corrected binary at
05:43 UTC. This supports an execution-context explanation for that error while
leaving its exact mechanism unproven. The code also now handles diagnostic-query
failure correctly if it recurs while actual reads remain usable.

The remaining demonstrated problem is zero software-reported incoming bytes in
complete status-reply windows. No parser rejection occurred because no bytes
reached it. This does not prove physical transmission, electrical silence, or a
scanner/adapter/cable fault. The optional angle and continuous-output stages remain
unverified because the documented prerequisite reply is missing. No handshake was
bypassed to force them.

The operator's earlier blinking-Keyspan observation is retained as an observation,
not evidence of a serial reply. No wiring, driver, Windows security, baud, or
unrelated scanner-setting change occurred. COM7 is closed; no listener or run is
left queued.

Files: `rx.bin`, `events.jsonl`, `result.json`, `console.log`, `build-manifest.json`.
The comparison run and original failure remain in their separate directories.
