# Protocol and hardware findings

Reviewed all four requested references before implementation on 2026-09-06.

* Target is LMS200-30106, part 1015850; 24 V ±15%, at least 2.5 A external supply.
  USB-C alone cannot supply power or carry the LMS serial protocol.
* The 2008 supplement §1.1 p3 corrects scanner data pins 3=TD+/TxD and 4=TD−.
  Quick Manual p8 uses the old assignment. Cross by signal, not that obsolete numeric diagram.
* Telegram Listing §9 p107 gives a nonstandard byte-wise CRC with polynomial 0x8005,
  one shift per input byte, previous/current byte XOR, initial zero, little-endian output.
* ACK 06 and NAK 15 are individual bytes. ACK alone never completes a command.
* 0.25° standard output is restricted to 100°, physically 40° through 140°. Scans run
  right to left viewed from above, with 0° at the right and 90° forward.
* Mode 0D in the 2001 setup example is reserved in the 2006 listing. Use documented
  mode 02. Preserve the read configuration, change only mode, units, and optional indices.
* 75 Hz is the mirror rate. Complete 0.5° scans take two rotations and 0.25° four.
* Some listing prose has evident degree/unit/length/example typos. Decisions and exact
  field sources are recorded in PROTOCOL.md and references/README.md.
* Reference PDFs remain in ignored local research storage and are not redistributed.
