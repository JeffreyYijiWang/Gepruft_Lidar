# O_NDELAY and serial-open flags check

Read-only code/log investigation, 2026-09-07. No serial port was opened, no hardware
command was sent, and no communication implementation was changed for this check.

## Finding

The historical `O_NDELAY` workaround is real, but there is no missing equivalent
flag established in the current COM7 path. The latest executable uses native
Windows `CreateFileW`, not POSIX `open()`. Its observed failure is absent incoming
bytes after a successful open, not a process blocked while opening a tty.

## What the historical report establishes

The [2011 author's account](https://thebattlegoeson.blogspot.com/2011/06/xyz.html)
adds `O_NDELAY` to old SickToolbox's Linux serial `open()`, adds a startup delay,
and rebuilds the driver. The [2012 follow-up report](https://robotics.stackexchange.com/questions/37303/problem-using-sick-lms200-laser-with-sicktoolbox)
describes hanging at the message that it is opening `/dev/ttyUSB0`; the author
reports success after rebuilding the wrapper against the changed library. These
are first-person reports, not a general SICK or Keyspan specification. They do
not isolate the effect of every change or establish a Windows-driver fix.

[Linux open(2)](https://man7.org/linux/man-pages/man2/open.2.html) documents
`O_NONBLOCK`/`O_NDELAY` as nonblocking operation. For terminals, this can avoid
waiting during open; subsequent nonblocking reads must be handled appropriately.
[termios(3)](https://man7.org/linux/man-pages/man3/termios.3.html) defines `CLOCAL`
as ignoring modem-control lines and `CREAD` as enabling the receiver. It also
warns that nonblocking reads can return immediately despite VMIN/VTIME settings.
Adding the flag blindly to a blocking read loop is therefore not a complete fix.

## Actual repository paths

| Implementation | Inspected behavior | Applicability |
|---|---|---|
| Current native Windows diagnostic, `tools/lms200_native/win_serial.cpp:348` | `CreateFileW` on `\\.\COM7`, read/write access, share mode 0, `OPEN_EXISTING`, `FILE_FLAG_OVERLAPPED`, null template/security. Separate read/write OVERLAPPED state; completion obtained before reuse. | Correct documented Windows open pattern. `O_NDELAY` is not a `CreateFileW` flag. |
| Installed Windows pyserial, `.venv/Lib/site-packages/serial/serialwin32.py:54` | Same access/share/open/overlapped choices. | Also Windows; does not use Linux `open()` flags. |
| Installed Linux pyserial, `serialposix.py:322` | Already opens with `O_RDWR | O_NOCTTY | O_NONBLOCK`; sets `CLOCAL | CREAD` at403; uses `select()` at565 and handles EAGAIN/EWOULDBLOCK. | The relevant nonblocking-open behavior is already present. The separate `VTIMESerial` class clears nonblocking for its own read strategy; the project does not select it. |
| Retained SickToolbox reference, `tmp/pdfs/sicktoolbox.cc:2334` | Already includes `O_RDWR | O_NOCTTY | O_NDELAY`, then optional `sleep(delay)`. | Reference source only; not the executable used in COM7 captures. |
| Retained original LMSAPI Unix source, `tmp/pdfs/independent-audit-followup/lmsapi_serial_unix.c:23` | Already includes `O_NDELAY`, clears it after open, and temporarily sets FNDELAY for reads. | Dormant Unix backend, not the original Windows DLL or current diagnostic. Other inherited-termios/return-value defects in this source are separate from the missing-flag hypothesis. |

Microsoft's [communications-resource handle requirements](https://learn.microsoft.com/en-us/windows/win32/devio/communications-resource-handles)
specify exclusive share mode, `OPEN_EXISTING`, and null template, and permit
overlapped I/O. `FILE_FLAG_OVERLAPPED` enables asynchronous operations; it is not
an exact Windows spelling of POSIX carrier-wait behavior. The native program
separately configures/readbacks disabled CTS/DSR/software flow control and disabled
DSR sensitivity (`win_serial.cpp:359` onward).

## What the captures establish

The corrected run's `run_begin` event is at elapsed 2 ms, `port_opened` after full
settings setup at 8 ms, and `reader_armed_before_tx` at 10 ms. Its three post-drain
read windows last 5024, 5024, and 5010 ms. The reader is healthy at normal close;
RX is zero throughout. See
[the preserved result](diagnostics/native-reader-fix-COM7-20260907T054336Z/SUMMARY.md).

The initial error 5 was a later Windows status-query exception, after open and a
completed write, not a Linux open wait. The old code could also mask an underlying
read error with that query exception; its exact original cause remains unknown.
Two subsequent outside-sandbox runs completed their windows without that error.

No code change to open flags is justified by these findings. Keyspan-specific
driver behavior is not completely ruled out, but an `O_NDELAY` omission does not
explain the tested Windows path. The remaining unresolved observation is zero
software-reported RX despite complete listening windows. Neither the open flags
nor driver-accepted write counts prove physical serial transmission or scanner
receipt. Changing to Linux/Docker would introduce a different test path rather
than apply a missing flag to the executable that ran.
