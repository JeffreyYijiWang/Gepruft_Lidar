# Fresh-start evidence, 2026-09-08

This directory contains newly collected host evidence and an offline packet
derivation. No live serial test was run. Physical confirmations are outstanding;
no prior conversation's driver, loopback, power or wiring conclusions establish
the present state.

- `windows-inventory.json`: native Windows CIM/PnP/registry and INF inspection,
  collected with `scripts/inspect-keyspan.ps1`. Includes the COM7-to-USB parent.
- `driver-comparison.json`: SHA-256 comparison of the freshly downloaded official
  Windows 10/11 package against the two installed INF and two SYS files; all match.
- `status-crc-verification.json`: offline rolling-word CRC derivation from SICK's
  published algorithm and comparison with the project implementation.
- `verify_status_crc.py`: reproducible offline calculation; creates its output
  exclusively, so use a separate directory for a new verification run.

Downloaded PDFs, driver ZIP/MSI/CAB and renderings remain in the ignored
`.local/fresh-diagnosis-20260908/` directory and are not redistributed. The MSI was
opened with MSIDBOPEN_READONLY and its CAB extracted without installer execution.
The local extraction script and MSI table metadata are retained there too.

Final verification: 195 tests passed, 2 expected skips; Ruff format/lint, mypy,
and `git diff --check` passed. Tests use synthetic serial fixtures, including the
reset experiment's existing tests; no reset or other serial command was sent.

See [the investigation and staged procedure](../../FRESH_START_DIAGNOSIS.md) for
manufacturer citations, uncertainties, safe connector orientation and exact
commands. The next required observation is a newly confirmed isolated Keyspan
loopback setup, followed by its measured result. No live run is queued.
