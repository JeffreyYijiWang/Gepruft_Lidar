# Native Windows LMS200 diagnostic

This separate C++17 executable uses Win32 serial APIs directly. It does not load
the production Python service, pyserial, LMSAPI DLL, C#, .NET, WSL, or Docker for
serial communication. Build automation uses PowerShell; the produced executable
runs directly on Windows. Production driver behavior is unchanged.

## Scope and authorization

The operator explicitly requested status, an optional 100-degree/1-degree variant,
continuous output, ten seconds of capture, and a stop. Before a live run, obtain
fresh confirmation that the scanner is powered on, startup is complete, all other
COM7 applications are closed, and whether to enable the optional variant. Do not
change wiring. `--run --confirm-hardware` records that these confirmations were
provided; the executable cannot sense power, LEDs, or operator confirmation itself.
Without `--run`, it only displays the plan. `--self-test` cannot be combined with
live options and never constructs the serial transport.

## Commands and source requirements

Sources are the [Quick Manual v1.0, June 2001](https://www.danarte.es/archivos/pdf/1866.pdf)
(QM) and [LMS2xx Telegram Listing 8007954/Q501](https://sicktoolbox.sourceforge.net/docs/sick-lms-telegram-listing.pdf)
(TL). Page numbers below are the printed pages, which match PDF page indices plus
one for these files. The full QM was read, including diagrams and examples; the
detailed TL sections were checked for framing, timings, semantics, and CRC.

| Stage | Exact binary bytes, including low/high CRC | Confirmation | Source |
|---|---|---|---|
| Status | `02 00 01 00 31 15 12` | `06`, then CRC-valid `B1` with supported status layout | QM C.2 p9; TL §7.6 pp52–57 |
| Optional variant | `02 00 05 00 3B 64 00 64 00 1D 0F` | `06`, then `BB 01 64 00 64 00` plus acceptable status | QM C.5 p11; TL §7.16 p66 |
| Start continuous | `02 00 02 00 20 24 34 08` | `06`, then `A0 00` plus acceptable status | QM C.7 p12; TL §7.4 pp40–45 |
| Capture | No TX for 10 s after successful start confirmation | Preserve all RX, decode `B0` when possible | QM p13; TL §7.5 pp47–51 |
| Stop | `02 00 02 00 20 25 35 08` | `06`, then `A0 00` plus acceptable status | QM C.9 p14; TL §7.4 pp40–45 |

The CRC polynomial is `8005`, with the byte-wise algorithm in TL §9 p107; it is
not a conventional eight-shifts-per-byte CRC16/IBM routine. The four numeric CRCs
are respectively `1215`, `0F1D`, `0834`, `0835`, serialized least significant byte
first. Command arrays have explicit lengths 7, 11, 8, 8; each command uses one
`WriteFile`, with no ASCII hex, newline, `strlen`, per-byte delay, or partial-write retry.

TL §4 pp21–25 defines STX/address/little-endian payload length/payload/low-high CRC.
The response payload includes its command and trailing status. `02 80` and `02 81`
are binary STX/address pairs, not text: response addresses have the scanner address
with bit 7 set. QM examples use `81`; TL documents address behavior and the
broadcast-address case in §10.8 p124. This diagnostic accepts response address `80`
or `81` for its fixed address-zero requests. Other addresses remain preserved and
reported but cannot confirm a transaction. It does not discover or change an address.

QM p12/p14 directs stopping continuous output before further settings. This minimal
sequence requires the initial B1 mode to be monitoring on request (`25`); a different
mode aborts before variant/start, retaining evidence rather than adding a pre-stop
or configuration sequence. QM C.5/TL §7.16 do not state an installation/password
precondition for the variant request. No installation, baud, measurement-unit,
range, field, reset, or general configuration command is sent. If requested, the
variant change is recorded with the original B1 geometry and is not automatically
restored by an extra command.

TL §4.3 p24 allows ACK/NAK within 60 ms, a maximum host inter-byte gap of 6 ms,
scanner inter-byte gap of 14 ms, and at least 30 ms after NAK. Mode changes can
take up to 3 s. This diagnostic uses one whole-buffer write, a 1 s write deadline,
a separate 1 s output-drain deadline, then up to 5 s for the full handshake. A
successful or explicitly rejected exchange may finish early. Only entirely silent,
fully written and drained status exchanges may retry, at most three total attempts.
No retries follow partial writes, received but rejected bytes, NAK, or any variant,
start, or stop command. A host API cannot establish actual on-wire byte timing.

TL §8 p106 defines status severity in bits 0–2: `0` OK, `1` information, `2` warning,
`3` error, `4` fatal, remaining values reserved. Source bits, restart input,
implausibility, and pollution flags are reported separately. Status `10` is
compatible with an OK type-6 scanner. B1's separate error byte (TL p53) and a baud
code other than 9600 also prevent this sequence from continuing. Warnings are
reported; errors/fatal/reserved severity cannot confirm an accepted command.

The TL B1 field table sums to 146 data bytes, while its reply table says 152. Two
explicit layouts are supported. The additional six reserved bytes before block E
in the 152-byte layout are corroborated by SICK Toolbox source already retained
in this repository's references; they are not established by QM alone. Unknown
layouts remain raw evidence and do not authorize settings/start. Standard B0
sample counts, unit, geometry, status, and optional index bytes are checked. No
distance-value interpretation or scan reconstruction is substituted for raw capture.

## Serial and evidence behavior

- `CreateFileW` opens COM7 exclusively with overlapped I/O, fixed 9600/8-N-1.
  The DCB is explicitly assigned, including disabled CTS/DSR/XON/XOFF, disabled
  DSR sensitivity, disabled null deletion/error replacement, and disabled DTR/RTS.
  `GetCommState`, timeouts, modem input bits, and UART-error masks are logged.
- One read worker issues its first `ReadFile` before TX is permitted. It stays
  active through output drain, capture, and stop. There is a 200 ms passive
  pre-TX interval, with no receive reset or handle reopen.
- Raw bytes are flushed to `rx.bin` before JSON logging and parsing. Separate
  OS-delivered, confirmed-saved, and decoder-fed counts preserve error-path evidence.
  UART flags such as framing/parity/overrun errors are observations, not diagnoses.
- There is no `PurgeComm`, `SetupComm`, or `FlushFileBuffers`. Output drain polls
  `ClearCommError`/`cbOutQue` without deleting bytes. Queue zero and a completed
  Windows write are driver evidence, not proof of physical DB9 transmission.
- Fragmented frames survive empty reads through the whole exchange. Multiple
  frames and ACK/frame combinations are handled. Raw capture is never rewritten
  by resynchronization. Terminal recovery is labeled and cannot retroactively
  confirm a live exchange. Ambiguous control bytes found after corruption cannot
  serve as ACK/NAK in a handshake.
- A transaction needs an unambiguous ACK followed by a complete matching frame
  beginning after its RX boundary, with accepted address, CRC, layout, result,
  and status. No protocol transaction IDs exist; timing alone does not prove
  causation. Start and stop both reply `A0`, so after an unconfirmed start a valid
  cleanup response is reported separately and stopping remains ambiguous.
- If start might have been sent, exceptions, failed replies, and Ctrl+C cause one
  bounded stop attempt. Cleanup logging is best effort so disk/log failure cannot
  prevent this exact stop write. A failed reader is not restarted; a cleanup write
  can be attempted, but stop confirmation is then unavailable.
- A failed `ClearCommError` or modem-status query is logged independently from
  `ReadFile` completion. Missing queues/UART flags/modem inputs are `null`; an
  unavailable queue cannot confirm drain. Diagnostic-query failure alone leaves
  the reader active. A real read-completion failure is recorded first and cannot
  be hidden by a subsequent status query. No retry or next settings command is
  permitted without the existing successful drain/ACK/reply checks.
- Cancellation retains each buffer/OVERLAPPED until OS completion. A driver that
  ignores cancellation for 2 s triggers fatal exit 70; an outer 75 s watchdog
  covers otherwise stuck APIs and exits 71. Forced process termination, closing
  the console window, or such driver failure cannot guarantee the stop. A result
  left with `state: running` is incomplete evidence, never a success report.

## Build and run

From repository-root PowerShell:

```powershell
& .\tools\lms200_native\build.ps1
& .\tmp\native-lms200\lms200-native.exe --self-test
& .\tmp\native-lms200\lms200-native.exe
```

The build uses the native MinGW compiler at `C:\msys64\ucrt64\bin\g++.exe`,
static C++ runtime linkage, C++17, and warnings treated as errors. It produces
an x64 Windows executable and a SHA256 manifest of sources, compiler identity,
options, and executable. Check the manifest after the final build, before live use.
Builds are also archived by executable SHA256 under `tmp/native-lms200/archive`;
new archives contain the matching source inputs as well as executable and manifest.
Offline tests include exact manual command/reply CRCs, both response addresses,
fragmentation, corrupt data, B1 profiles, scan sizes, ACK ordering, bounded status
retry, optional settings, and cleanup after uncertain start/interruption/exceptions.
Synthetic fixtures are explicitly identified in the tests.

Only after the fresh confirmations requested above, run one of:

```powershell
& .\tmp\native-lms200\lms200-native.exe --run --confirm-hardware
& .\tmp\native-lms200\lms200-native.exe --run --confirm-hardware --set-100deg-1deg
```

For a separate ten-second passive listener with no transmitted command:

```powershell
& .\tmp\native-lms200\lms200-native.exe --run --confirm-hardware --listen-only
```

The passive listener saves the same raw evidence, can stop on Ctrl+C, and closes
COM7 at its deadline. Its completion says that listening finished; it does not
claim a status response or scan data. It cannot be combined with the variant flag.

Run hardware access from ordinary native Windows PowerShell outside a restricted
agent execution sandbox. In the 2026-09-07 comparison, the identical executable
failed with access denied in the sandbox but kept its reader alive for the full
three five-second windows outside it. This supports an execution-context cause
for that failure; it does not prove the underlying permission mechanism or rule
out a transient driver condition. It does not establish scanner communication.
No Windows security-setting change or driver reinstall is part of this workaround.

## Byte-order audit, 2026-09-07

No `htons`, `ntohs`, `htonl`, `ntohl`, byte-swap routine, or direct struct-to-serial
write was found in the active C++ diagnostic, Python framing/transport, or bridge.
Microsoft documents [htons](https://learn.microsoft.com/en-us/windows/win32/api/winsock/nf-winsock-htons)
as producing big-endian network order; it is not called in these telegram paths.
The native arrays are copied unchanged to `WriteFile(bytes.data(), bytes.size())`.
The native reader reconstructs words as `low | (high << 8)`. Python framing uses
explicit `little`, and typed numeric fields use `<H`/`<HH`. Bridge/TCP data paths
forward byte buffers without numerical conversion; their separate JSON control
connection is not the scanner telegram stream. Docker runs that code and adds no
telegram byte-order conversion. Running Linux in Docker does not itself swap a
telegram's bytes. `DCB`/`COMMTIMEOUTS` structures configure Windows and are never
written as scanner commands. The original LMSAPI also uses explicit low/high
serialization; its separate known configuration-length defect remains unrelated.

`--output NEW_DIRECTORY` selects a new evidence directory and refuses to overwrite
an existing one. The default is `docs/diagnostics/native-COM7-<UTC>`. It contains
`rx.bin`, timestamped `events.jsonl`, and `result.json`. `--led-observation TEXT`
records explicitly labeled operator observations, never command acceptance.
Copy the matching `build-manifest.json` into the run directory after execution.
Exit 0 requires the completed sequence and valid scan data; exit 3 preserves an
incomplete/failed sequence or a completed sequence without valid scans. Exit 2
is setup/reporting failure; fatal exits 70/71 require reviewing the saved partial
evidence. No failure by itself establishes a scanner, cable, or adapter fault.
