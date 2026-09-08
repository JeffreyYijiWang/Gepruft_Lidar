# LMSAPI 1.1c evaluation and offline integration

Historical evaluation below. The operator subsequently authorized a separate original
DLL experiment retaining its configuration/retry behavior; see
[LMSAPI_EXPERIMENT.md](LMSAPI_EXPERIMENT.md). The production driver remains unchanged.

Inspected and tested 2026-09-07 UTC (2026-09-06 EDT). The operator supplied
`C:\Users\Jeffr\Downloads\lmsapi_1.1c\lmsapi` and its original ZIP, and asked to run
LMSAPI and apply it to this project. The operator explicitly confirmed the scanner
**powered off** and reported that the Keyspan, black adapter and scanner cable were
connected again. Connector wiring and the black adapter model were not newly verified.

**Executed:** a native 64-bit Windows build of LMSAPI's original, unchanged CRC function,
as an optional offline comparison command in this repository. Both published telegram
examples and all 522 synthetic differential inputs agree with our implementation.
**No COM port was opened. No scanner command, configuration, scan or retry was sent.**
The GUI demos and full library have not been executed. No hardware test is armed;
keep the scanner off pending a separately prepared, supervised test.

## Package identity and provenance

[SourceForge project](https://sourceforge.net/projects/lmsapi/) lists LMSAPI as a beta
C interface for the SICK LMS200, under the BSD License. Its
[file listing](https://sourceforge.net/projects/lmsapi/files/) identifies
`lmsapi_1.1c.zip` (displayed as 9.1 MB). This is the Universidad Manuela Beltrán /
Francisco León project, separate from SICK's original MST Demo.

| Item | Observed value |
| --- | --- |
| Operator-supplied archive | `C:\Users\Jeffr\Downloads\lmsapi_1.1c.zip` |
| Inspection date | 2026-09-07 UTC |
| File modification time | 2026-09-07 03:36:51 UTC; not independently established as download completion |
| Bytes | 9,091,205 |
| SHA-256 | `c8d2b5c38cc497f0ea7032e2c73a689c9bb52846497afdb4809ebf81d4898434` |
| ZIP entries / total uncompressed bytes | 444 / 25,469,390 |
| Existing extracted files vs ZIP | All archived files matched byte for byte |
| Original native DLL | `lmsapi/libDLL/lmsapi.dll`, PE i386 (32-bit) |
| Original DLL SHA-256 | `534f7b6fe9212f7592f409ccfafc94d7cd618cb3bb49175823e911186dad437c` |
| Original native DLL imports | `KERNEL32.dll`, `msvcrt.dll`, `USER32.dll` |

The local archive hash identifies the reviewed bytes. No publisher signature or
independent published checksum was established; the public filename and the internal
project attribution agree with the user's reported origin. The SourceForge root
pages were accessible; the nested `files/lmsapi/` page failed in the web reader.
No replacement package was downloaded from another site.

The archive was inspected before our extraction: no absolute paths, parent traversal,
drive/stream paths, symbolic links or Windows case-colliding entries were accepted.
The tool copies the original ZIP and extracts only `src/lmsapi_crc.c` into a fresh
directory. It never extracts into repository source or overwrites an earlier build.

Local retained package/build: `third_party/lmsapi/crc-check-20260907/`, excluded from
Git and Docker context. It contains the ZIP, archive listing, original CRC source
with its license notice, our small ABI header, the compiled CRC-only DLL and build log.
All bundled executables and the rest of the source remain in the user's Downloads
extraction and inside the retained ZIP; they were not copied into our production code.

## Actual contents and license

Paths below are relative to the package's `lmsapi/` directory.

| Category | Examples |
| --- | --- |
| C library source | `src/lmsapi_sensor.c`, `src/lmsapi_serial_win.c`, `src/lmsapi_serial_unix.c`, `src/lmsapi_crc.c`, `src/lmsapi_console.c` |
| Headers / programmer manual | `include/lmsapi_*.h`, `include/stdint.h` |
| Native library | `libDLL/lmsapi.dll`, import library `liblmsapi.a`, exports `liblmsapi.def` |
| Managed wrapper | `dot_net_component/LMSAPIcomponent.dll` and its C# project/source |
| Compiled demo applications | `demos/bin/LMSAPI_csharp.exe`, `LMSAPI3D.exe`, `pruebaLMS200.exe` |
| Example source | `demos/sources/LMSAPI_csharp/`, `LMSAPI3D/`, `prueba_basic/`, `data_test/main.cpp` |
| 3D demo dependencies | `IrrlichtLib.dll`, `Irrlicht.NET.dll`, `Irrlicht.Extensions.dll` |
| Documentation | `docs/html/`, `docs/rtf/refman.rtf`, `include/lmsapi_manual.h` |
| Build projects | Code::Blocks `.cbp`, Visual Studio `.sln` / `.csproj` / `.vbproj` |

The core source headers and `docs/html/license.html` contain a Spanish BSD-style
three-condition license (copyright 2007 Francisco León, Universidad Manuela Beltrán).
It permits inspection, use and modification while requiring retained notices and
disclaimers, and forbids unauthorized author endorsement. The complete original
notice remains in the locally compiled source. The bundled historical `stdint.h`
states a public-domain grant by its contributor. Separate Irrlicht binary licensing
was not audited; none of those components was executed or redistributed.

## Connection behavior found in source

These findings concern the included source; the original DLL was not disassembled
to establish that every routine is binary-equivalent to it.

| Source location | Finding and consequence |
| --- | --- |
| `src/lmsapi_sensor.c:660`, `lmsapi_open_terminal` | Opens the requested COM number at 9600/8-N-1, then calls `lmsapi_config`, `lmsapi_set_resolution` and model identification. This is an active configuration operation. |
| `src/lmsapi_sensor.c:301` | Configuration entry sends `20 00` plus the documented password. Outside the existing one-status-request boundary. |
| `src/lmsapi_sensor.c:557` | Reads configuration (`74`), modifies range/intensity fields, then writes configuration (`77`). |
| `src/lmsapi_sensor.c:368` | Sends variant command `3B` with requested angular width/resolution. |
| `src/lmsapi_sensor.c:245`, `include/lmsapi_config.h` | `lmsapi_send_command` retries up to `LMSAPI_MAX_TRIES`, defined as 10. It does not meet the no-automatic-retry requirement. |
| `src/lmsapi_sensor.c:63` | Header recognition accepts `02 80` only. The project's documented `02 81` startup/response profile would be rejected by this parser. |
| `include/lmsapi_config.h`, sensor parser | Names `ACK=0xA0` and `NACK=0x92` refer to framed response codes. These do not replace standalone serial `06` ACK / `15` NAK evidence. |
| `src/lmsapi_serial_win.c:76` | Uses `CreateFile("COM%d", ...)`; sets baud/data/parity/stop fields but leaves inherited flow-control flags in the DCB. Computed `ucSet` values are never applied to those flags. No-flow-control behavior is not guaranteed. |
| `src/lmsapi_serial_win.c:87` | Checks `CreateFile` result against NULL instead of `INVALID_HANDLE_VALUE`. Later calls can still fail; this is an error-handling defect, not proof it always reports success. |
| `src/lmsapi_serial_win.c:150` | The single-byte write helper returns 1 regardless of actual write success, and the block writer increments its count unconditionally. A return of 7 cannot establish seven driver-accepted bytes in this library. |
| `src/lmsapi_serial_win.c:204` | Pending reads wait but do not obtain the completed byte count with `GetOverlappedResult`. This weakens receive evidence. No bounded output-flush API is exported. |
| `demos/sources/LMSAPI_csharp/LMSAPI_csharp/Form1.cs`, `request_laser_data` | The measurement action creates a connection (therefore configures the scanner) and then requests measurements. |

These behaviors prevent substituting the bundled library for the current guarded
hardware diagnostic. Importing it as the production transport would also lose our
single serial owner, timestamped raw capture, ACK requirements and profile handling.
No existing protocol/state-machine/transport implementation was replaced.

## Windows and COM7

`include/lmsapi_manual.h` documents Windows 98/NT/2000/XP/Vista or later and .NET
Framework 2.0 for the C# GUI. This old wording does not verify modern Windows 11
compatibility. The native DLL is 32-bit; it cannot be loaded into this project's
64-bit Python process. The managed wrapper project defaults to AnyCPU, which does
not make the native DLL 64-bit. No .NET feature, legacy runtime or driver was installed.

COM7 is supported by the inspected code: the C# selector contains numbers 1–20;
the handler passes `SelectedIndex + 1`, and the native layer formats `COM7` for 7.
The Visual Basic demo explicitly lists COM7 as well. No live COM7 open was attempted.
Port choices beyond 9 are not evidence of working support: the native source does
not use the extended Windows device-path form. No Windows COM assignment was changed.

The newly built **CRC-only** DLL is PE x86-64 and ran successfully in native Windows
Python 3.12.14. Only `lmsapi_create_crc` is exported. Its imports contain no serial
open/read/write/configuration calls. This establishes that this isolated routine
runs here, not that the complete legacy demo works.

## Applied code and results

`src/lms200/lmsapi_check.py` is an optional offline tool. It requires the exact
reviewed archive hash, validates the archive listing, preserves original source,
and compiles **only** `lmsapi_crc.c` with the existing native GCC 14.2.0. A minimal
local header supplies standard modern integer types and the exported CRC signature;
the CRC function itself is unchanged. The old header bundle contains 32-bit pointer
typedefs, so the isolated build does not use it or purport to port the entire library.
The compiled routine is called through ctypes with explicit C ABI argument types.
There are no serial or scanner-command options and no import of the hardware service.

| Offline test | Result |
| --- | --- |
| Published status request `02 00 01 00 31 15 12` | LMSAPI and project CRC both `1215`, wire `15 12` |
| Published 29-byte startup example | LMSAPI and project CRC both `5A64`, matching the printed checksum |
| Synthetic inputs | 522 comparisons, zero differences; includes empty, all single bytes and longer inputs |
| Existing direct-test RX `F0 39 14 31 21 31 01` | Zero complete frame candidates, zero valid frames; no receive CRC can be claimed |
| New hardware communication | None; COM7 unopened, TX 0 |

The archive, C source, local header, built DLL and input capture hashes are recorded
in [the offline report](diagnostics/lmsapi-offline-20260907.json). Original hardware
captures were read without modification. Saved frames are located by our project
framer and, if present, checked with LMSAPI's CRC; this is not execution of LMSAPI's
restrictive receive parser. The selected direct capture contained no such frames.
CRC agreement does not establish cable wiring, grounding or scanner health.

To repeat the **offline** check with new output paths from the repository root:

```powershell
.\.venv\Scripts\python.exe -m lms200.lmsapi_check `
  --archive 'C:\Users\Jeffr\Downloads\lmsapi_1.1c.zip' `
  --workdir third_party/lmsapi/crc-check-repeat `
  --report docs/diagnostics/lmsapi-offline-repeat.json `
  --compiler 'C:\msys64\ucrt64\bin\gcc.exe' `
  --capture docs/diagnostics/direct-COM7-20260907T030336Z.jsonl
```

The tool refuses existing work/report paths. It installs nothing and runs neither
package scripts nor the precompiled demo/DLL. Unit tests cover unreviewed archive
rejection, traversal/case collision rejection, capture boundaries, noise/bad CRC,
preservation of input logs and detection of a deliberately wrong CRC function.
Validation: 110 tests passed, 2 skipped; Ruff formatting/lint and mypy passed.
Two existing dependency deprecation warnings remain.

## Before a future power-on instruction

There is no prepared live LMSAPI test in this change. Do not click its measurement
or connection actions with the scanner attached under the current status-only
authorization. Its configuration/retry behavior requires a different reviewed
procedure; merely choosing COM7 does not make it read-only.

The already failed isolator-bypass test remains the latest physical evidence. The
black adapter's reintroduction does not explain or resolve the earlier direct-link
failure. Its identity and wiring still need verification. Any further wiring check
requires explicit power-off/disconnection confirmation; no connection was changed
remotely and no physical step is assumed complete. A software package cannot verify
the cable crossover or signal ground by itself.

A later authorized passive/status attempt must first confirm the actual connection,
normal connector fit, no jumpers and exclusive COM7 ownership. For our existing
`direct-test`, the isolator must be removed and all six direct-connection conditions
confirmed; that guard must not be bypassed for the current black-adapter setup.
Only after a listener reports open should the operator be asked to power on, and
startup completion must again be confirmed before any permitted status request.
