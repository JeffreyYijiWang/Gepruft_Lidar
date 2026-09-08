# Original LMSAPI experiment (separate backend)

## Authorization and scope, 2026-09-07 UTC

After the offline evaluation, the operator explicitly requested an independent LMSAPI
integration retaining its configuration-on-connect behavior, automatic retries,
unreliable write-count reporting and rejection of the `02 81` receive header, then
asked to run it. This authorizes those behaviors **for this opt-in experiment** and
supersedes the earlier status-only/no-retry restriction for this run. It does not
alter the production driver's defaults or authorize a baud search/continuous scan.

The operator separately confirmed: scanner OFF; computer → USB → Keyspan → black
adapter → gray cable → scanner; connectors normally fitted; no pin jumpers and
scanner data pins 7–8 open; all other COM7 programs closed. These are operator
confirmations. The black adapter's exact model/function and cable continuity remain
unverified. Nothing was disconnected or rewired by software.

## Implementation

`python -m lms200.lmsapi_experiment` is the separate command, tested in the current
source checkout. Package metadata also registers `lms200-lmsapi-experiment` for a
future package install. There is no integration into the production
state machine, API or streaming UI; this command must be the only COM7 owner.

`prepare` verifies the previously reviewed archive SHA-256, inspects all archive
paths, copies the **original unmodified** `libDLL/lmsapi.dll` and its license, and
builds the project-owned `native/LmsapiRunner.cs` using the already installed .NET
Framework compiler with `/platform:x86`. Python remains 64-bit and communicates
with the separate process through JSON stdout. No new runtime/driver installation,
administrator execution, DLL registration or security change is needed.

| Artifact | Identity |
| --- | --- |
| ZIP | `lmsapi_1.1c.zip`, 9,091,205 bytes |
| ZIP SHA-256 | `c8d2b5c38cc497f0ea7032e2c73a689c9bb52846497afdb4809ebf81d4898434` |
| Original DLL SHA-256 | `534f7b6fe9212f7592f409ccfafc94d7cd618cb3bb49175823e911186dad437c` |
| Prepared bundle | `third_party/lmsapi/original-runner-20260907/` (Git/Docker ignored) |
| Build provenance | Bundle `manifest.json`, including source/executable hashes and compiler command |
| License and source audit | [LMSAPI_EVALUATION.md](LMSAPI_EVALUATION.md) |

The original DLL is loaded without changes, using C calling convention and explicit
P/Invoke types. Its own console callback is retained and logged. No parser, serial
writer, retry limit, configuration logic, DTR/RTS or inherited flow-control flags
are repaired or substituted for this comparison. Nominal serial format is 9600/8-N-1;
the original DLL does not provide reliable evidence of its inherited handshake state.

## Test sequence

1. Refuse execution without both `--confirm-physical-setup` and
   `--allow-legacy-configuration-and-retries`. Power-on, startup-complete, cancellation
   and output-log paths must all be fresh and distinct. The native helper independently
   checks its flags and marker paths before loading/opening the port.
2. Open COM7 through `lmsapi_serial_open_port(7, 9600, 0, 8, 1)` while the scanner is
   confirmed off. Log the library's return value, then announce `listener_ready`.
3. Only then ask the operator to power on. Create the power-on marker **after** the
   operator's explicit reply. Read passive bytes using the original DLL throughout;
   record returned chunks with UTC host-read timestamps. The legacy read-count caveat
   applies; these are DLL-reported bytes rather than an electrical capture.
4. Wait at least 65 seconds after power-on confirmation and for a separate explicit
   startup-complete reply (yellow off, green or red alone). Each operator wait is
   bounded to 300 seconds. No RX reset/reopen is inserted between phases.
5. Call `lmsapi_open_terminal(7, 180, 50, 8, 0)` **once**. It reuses its open handle,
   requests configuration mode, reads/modifies/writes configuration and selects
   180° / 0.5° / 8 m with intensity off, then identifies the model. The library may
   retry each internal command up to ten times. These are requested settings, not
   verified scanner settings until supported by a response.
6. If the connection pointer is non-null, make one outer `lmsapi_send_command` call
   with payload `31`, expecting `B1`. The library may retry it internally up to ten
   times. A null connection ends the experiment without this subsequent status call.
7. Close using the original library. No wrapper cleanup telegram, measurement request,
   continuous stream or outer reconnect/retry is issued. A 90-second watchdog bounds
   the whole active phase, including cleanup. The passive phase has a 610-second
   hard watchdog; Python also bounds the helper lifetime to 710 seconds. Termination
   releases process handles but cannot undo scanner settings already accepted.

A cancellation marker is checked during passive listening and between native calls.
It cannot interrupt a blocked original native call immediately; the watchdog bounds
that case. Interrupting the Python process terminates its helper and sends no further
wrapper command. Any interrupted/failed configuration can leave scanner settings
changed; no automatic restoration is attempted.

## Evidence limits and interpretation

The original DLL consumes internal active RX and hides its transmitted bytes. There
is no simultaneous second serial reader. The log records call intent, timestamps,
library messages, connection result and returned B1 payload. **Active TX byte count,
active raw RX byte count, standalone ACK/NAK and independently captured wire CRC are
unavailable**, represented as null rather than zero or success. Its overreported
write counts are not reclassified as successful physical transmission.

The returned status payload has no header/footer. The original library validates
CRC internally in the supplied implementation; the wrapper labels that as library
evidence. Our strict status decoder checks the returned payload's layout and fields
without fabricating a received wire frame. `library_status_succeeded` means the helper
exited successfully and the payload decoded. It is distinct from our normal
ACK-plus-independently-captured-CRC diagnostic criterion.

Passive bytes are evaluated by the project's framer after capture. Only a complete
length/CRC-valid telegram counts; noise and isolated bytes remain noise. The original
active parser continues to require `02 80`, as requested.

On null connection, decode failure, crash or timeout: stop and preserve evidence.
Do not silently switch parsers, remove the adapter, search baud or run another backend.
The result does not by itself distinguish wiring, interface selection, scanner state
and a limitation/defect in the original LMSAPI implementation.

## Commands

Preparation and the non-hardware original-DLL check:

```powershell
.\.venv\Scripts\python.exe -m lms200.lmsapi_experiment prepare `
  --archive 'C:\Users\Jeffr\Downloads\lmsapi_1.1c.zip' `
  --output third_party/lmsapi/NEW-original-runner
.\.venv\Scripts\python.exe -m lms200.lmsapi_experiment self-test `
  --bundle third_party/lmsapi/NEW-original-runner
```

The supervised live command below requires fresh paths and actual confirmations;
the flags are not a replacement for asking the operator:

```powershell
.\.venv\Scripts\python.exe -m lms200.lmsapi_experiment run `
  --bundle third_party/lmsapi/original-runner-20260907 `
  --log docs/diagnostics/NEW-lmsapi-original.jsonl `
  --power-on-file tmp/NEW-lmsapi-on `
  --startup-complete-file tmp/NEW-lmsapi-startup-complete `
  --cancel-file tmp/NEW-lmsapi-cancel `
  --confirm-physical-setup --allow-legacy-configuration-and-retries
```

At 03:55:03 UTC the original x86 DLL self-test passed: request CRC `1215` and
`serial_opened=false`. A separate native invocation without confirmation flags
refused before loading the DLL/opening any port. Evidence:
[lmsapi-original-self-test-20260907.jsonl](diagnostics/lmsapi-original-self-test-20260907.jsonl).
The completed live result follows below.

Validation before opening COM7: 123 tests passed, 2 skipped; Ruff formatting/lint
and mypy passed. The full test suite exposed an existing dashboard division-by-zero
when fast simulator scans share a clock tick. A two-line positive-interval guard in
`Device.snapshot()` and regression tests fix that telemetry calculation; serial
and protocol behavior are unaffected. Two existing dependency deprecations remain.

Refreshing the optional installed console entry with `pip install --no-deps
--no-build-isolation -e .` failed because this venv lacks `setuptools.build_meta`.
No build dependency was installed; the tested module command above works directly
and was used for the live attempt. This packaging issue did not affect the helper.

## Completed original-DLL hardware attempt

2026-09-07 03:57–03:59 UTC / 2026-09-06 23:57–23:59 EDT. **No working connection.**
One outer connection/configuration call failed; no outer retry was made. The black
adapter remained in the operator-confirmed chain. Original DLL SHA-256 matched the
reviewed package. The 90-second watchdog was not reached and no crash occurred.

| UTC | Event |
| --- | --- |
| 03:57:44.496 | COM7 open returned 1 |
| 03:57:44.500 | Passive listener ready; power-on requested afterwards |
| 03:58:10.942 | DLL-reported RX `C0`, before the operator's power-on confirmation marker |
| 03:58:37.243 | Explicit operator power-on confirmation recorded |
| 03:58:40.721 | DLL-reported RX `39 14 31 21 31 01` |
| 03:59:21.180 | Explicit startup-complete confirmation recorded: yellow OFF, green alone |
| 03:59:42.254 | Passive phase ended, 65.011 seconds after power-on confirmation |
| 03:59:42.256 | One `lmsapi_open_terminal(7,180,50,8,0)` call began |
| 03:59:43.558–03:59:55.147 | Ten failed-read messages during the original library's retry loop |
| 03:59:55.147 | Library reported timeout/no sensor response and configuration-mode entry error |
| 03:59:55.151 | Connection pointer null; close returned 1, `library_is_open=false` |
| 03:59:55.171 | Python recorded helper exit code 3 and unsuccessful experiment result |

| Test | Bytes transmitted | Bytes received | ACK/NAK | Valid frame | CRC | Interpretation |
| --- | --- | --- | --- | --- | --- | --- |
| Passive startup | 0 | DLL reported 7: `C0 39 14 31 21 31 01` | Neither in exposed passive bytes | None; no STX | Unavailable | No startup telegram established |
| Original LMSAPI connect/configure | Unavailable from DLL | Active raw bytes unavailable | Unavailable | No accepted reply reported; no active frame exposed | Unavailable | Ten failed-read attempts, then configuration-mode entry failure and null connection |
| Follow-up status | Not attempted | Not attempted | Not tested | Not tested | Not tested | Skipped because connection failed |

The active call took about 12.90 seconds. The ten failed-read callback messages
are observed; the interpretation as the ten internal attempts is consistent with
the reviewed source. Actual transmitted/received counts cannot be inferred from
them. The result is not proof of zero electrical RX or of exactly ten successful
transmissions. No post-connect status, measurement, continuous output, baud search
or cleanup telegram was issued by the wrapper.

The DLL reported failure **entering configuration mode**, before successful completion
of its settings sequence. No scanner settings change was verified. Because raw active
traffic and acceptance are hidden, do not assert that the scanner necessarily kept
all prior settings; no automatic restoration was attempted.

The process exited and its serial handle was released; a process inventory found no
remaining `LmsapiRunner`. The original backend is now available independently, but
this run did not establish communication. Remaining possibilities include signal-path
wiring/ground/interface selection or scanner state, as well as the original library's
parser/serial limitations. Do not label the black adapter or scanner as proven faulty.

Transcript (all exposed bytes, API events and library messages, original evidence retained):
[lmsapi-original-COM7-20260907035741Z.jsonl](diagnostics/lmsapi-original-COM7-20260907035741Z.jsonl).
Run ID: `cfc45bcc-fe47-4379-b385-65856b697428`. No further hardware attempt is queued.
