# Valid status versus deliberately reversed CRC

This separate, opt-in Windows experiment uses the Keyspan USA-19HS on COM7 at
9600 baud, eight data bits, no parity, one stop bit, parity checking disabled,
all hardware/software flow control off, and DTR/RTS disabled. The scanner must
already be powered and startup complete (allow up to 60 seconds after power-on).
Current operator confirmations are recorded in AGENTS.md. The operator reported
no measurement instrument attached. Electrical results remain **unverified** until
an actual capture is supplied.

## Exact scope and commands

Test A sends at most 20 copies of `02 00 01 00 31 15 12`. Only after twenty
completed silent attempts may Test B send at most 20 copies of
`02 00 01 00 31 12 15`. Destination remains the universal address 00. CRC over
`02 00 01 00 31` is 0x1215, correct little-endian bytes `15 12`; the deliberately
reversed bytes `12 15` encode 0x1512 and are invalid. No other byte is reversed.
No address discovery or scanner configuration command runs.

From the repository root, review the exact plan without opening serial:

```powershell
.\.venv\Scripts\python.exe -m lms200.crc_comparison
```

For a separately authorized run, with the current scanner connection and startup
confirmed, no loopback jumper, and all other COM7 owners closed, use a **new**
output directory. The flags attest to those conditions and the invalid-CRC test:

```powershell
.\.venv\Scripts\python.exe -m lms200.crc_comparison --run --confirm-powered-on-scanner-interface --confirm-reversed-crc --output docs/diagnostics/crc-comparison-NEW
```

One exclusive Windows handle remains open across both tests. Its dedicated reader
completes a read before the first transmission, persists raw bytes to `rx.bin`
and `events.jsonl` before parsing, and remains active through writes, TX drain,
waiting, and phase changes. Any received byte blocks further sends, including
noise, ACK, NAK, and partial frames. An already-started write cannot be recalled.
Bounded capture then preserves the reply: 250 ms idle allowance, at least one
second following an ACK, and a 15-second response ceiling. The sequence has a
60-second ceiling. Cleanup stops the reader and closes COM7; nothing is queued.

Each attempt checks actual `GetCommState` on that same handle, logs the seven-byte
buffer and write start/completion times, makes exactly one `serial.write(bytes)`
call, and drains TX with a bounded `flush()` and output-queue-zero check. There is
no byte-at-a-time loop, logging, sleeping, or flushing between bytes. No manual
start/stop bits are supplied. Pyserial's Windows open performs its own initial
purge; capture begins after open. No subsequent RX purge/reset/reopen occurs.
DCB mismatch, failed API/read/write/drain, stale reader, or short write prevents
further transmission and is recorded with available Windows error details.

Silent receive windows target 200–228 ms after drain, with at least 100 ms between
write starts; Windows scheduling may lengthen them. `result.json` reports each
test separately. Exit 0 requires a clean baseline status response or a standalone
NAK observed during Test B; silence or an unexpected response is exit 1. A reply
during a test is associated by time, not proven to belong to a particular attempt.

## Host timing versus electrical timing

At nominal 9600/8-N-1, a bit is 104.17 microseconds, a ten-bit character is
1.0417 ms, and seven characters take 7.2917 ms without extra idle. This total may
exceed 6 ms even with valid neighboring-character spacing. Neither total write
duration nor output queue zero measures the gaps on the RS-232 line.

The one-call design provides strong application-level evidence that the program
supplies a contiguous binary buffer. Windows DCB readback establishes what the
driver reports, not scanner receipt, adapter electrical output, or physical
framing/timing. USB and UART transmission occur downstream of that evidence.

The SICK manual specifies host intervals of at least 55 microseconds and at most
6 ms, and ACK/NAK within 60 ms. It does not precisely define the interval's edge
reference in that paragraph. Record the reference points below rather than
confusing extra idle time, the mandatory stop bit, and start-to-start spacing.
[SICK Telegram Listing, section 4.3, p24](https://sicktoolbox.sourceforge.net/docs/sick-lms-telegram-listing.pdf).

## Scanner-end measurement procedure

1. Identify the **data** connector, distinct from the power/I/O connector. With
   power removed and cables suitably isolated for continuity testing, follow the
   actual molded pin numbers and the applicable mating/rear-view drawing; the
   apparent left/right positions reverse between views. Verify Keyspan TX reaches
   scanner RX, scanner TX reaches Keyspan RX, and signal ground is continuous.
   The corrected LMS200 data pinout is RX pin 2, TX pin 3, signal GND pin 5.
   Keyspan DB9 TX pin 3 must reach LMS RX pin 2; LMS TX pin 3 must reach Keyspan
   RX pin 2. Leave scanner pins 7–8 open for RS-232. Do not blindly swap outputs
   or apply power to the data connector. The SICK supplement explicitly corrects
   the old pins 3/4 error.
   [SICK technical information, section 1.1, p3](https://www.sick.com/media/docs/3/33/933/technical_information_lms200_211_221_291_laser_measurement_systems_en_im0027933.pdf).
2. Use a suitable breakout/test point **at the scanner end of the complete,
   normally connected cable**. Capture CH1 at LMS RX pin 2 relative to signal
   ground pin 5, and CH2 at LMS TX pin 3 relative to pin 5. Use an oscilloscope
   rated for the bipolar RS-232 voltages, an RS-232 protocol analyzer, or a proper
   RS-232 receiver feeding a logic analyzer. Connect a scope ground only to a
   verified compatible ground; where this cannot be established, use an
   appropriately rated isolated/differential probe. Never defeat protective earth.
3. **Do not connect an ordinary TTL-only analyzer directly to RS-232.** For a
   MAX3232 receiver, monitor the lines through RIN1/RIN2, and connect the analyzer
   to ROUT1/ROUT2. A bare 16-pin MAX3232 uses RIN1 pin 13 → ROUT1 pin 12 and
   RIN2 pin 8 → ROUT2 pin 9, GND pin 15, VCC pin 16. Use a correctly built,
   powered board with its required capacitors and logic supply compatible with
   the analyzer. Check the actual board labels and schematic; never attach its
   DOUT transmitter outputs to the existing TX lines. The receiver adds load, so
   prefer a high-impedance RS-232-rated probe for signal-quality measurement.
   [TI MAX3232 data sheet](https://www.ti.com/lit/ds/symlink/max3232.pdf).
4. Arm capture **before Test A**. Sample at least 1 MS/s (higher rates improve
   edge timing), with pretrigger history and at least 100 ms after a request;
   longer captures preserve a complete status response. Trigger on the first
   request start bit and retain the original waveform, decoder export, instrument
   model, probe/receiver wiring, sample rate, threshold, and timestamps. Keep
   Test A and Test B captures clearly labeled. An instrument must be armed before
   a new explicitly requested software run; the completed test is not replayed
   automatically.
5. Decode at 9600 baud, 8 data bits, no parity, one stop bit, LSB first. On raw
   RS-232, idle/mark/logical 1 is negative and start/logical 0 is positive. After
   an RS-232-to-TTL receiver, idle is high and start low. Set the decoder polarity
   for the measured signal and avoid double inversion; decoder option names vary.
   [Saleae asynchronous serial guide](https://www.saleae.com/support/protocol-analyzers/analyzer-user-guides/using-async-serial).
6. At LMS RX, verify seven decoded bytes exactly `02 00 01 00 31 15 12` for
   Test A. Inspect individual characters for one start bit, eight data bits,
   no parity slot, and a stop bit. Measure the bit period as well as decoding it.
   For each of the six neighboring-character pairs record start times S[i] and
   S[i+1], and measured bit period T:

   | Measurement | Formula | Nominal back-to-back 9600/8-N-1 |
   |---|---|---|
   | Start-to-start interval | S[i+1] − S[i] | 1041.67 us |
   | Mark interval including mandatory stop | S[i+1] − (S[i] + 9T) | 104.17 us |
   | Additional idle after a full stop bit | S[i+1] − (S[i] + 10T) | 0 us |

   Report all six intervals, minimum and maximum, timing resolution, and the
   reference convention used for comparison with the 55 us–6 ms limit. Under the
   mark-interval convention compare that column with both limits. Do not declare
   zero **additional** idle a violation of the 55 us minimum: a mandatory stop
   bit is already about 104 us. If the acceptance decision depends on the edge
   convention, obtain SICK clarification. A measured idle pause greater than
   6 ms is unambiguous evidence of excessive delay.
7. Use the end of the final request stop bit as the reference for CH2. Record
   whether LMS TX starts activity within 60 ms, the measured latency, and every
   decoded return byte. Activity alone is not a valid ACK/NAK or CRC-valid reply.
   Preserve an unexpected response to the reversed CRC before interpreting it.

## Interpretation and report fields

| Observation at the scanner connector | Segment or condition to investigate |
|---|---|
| Request absent at LMS RX | Keyspan output, connector, complete cable/crossover, or signal ground |
| Request present but decoded incorrectly | Baud, polarity, RS-232/RS-422 selection, or signal quality |
| Request correct, LMS TX inactive | LMS interface selection, baud/configuration, startup state, or serial hardware |
| Request correct, LMS TX active, COM7 RX empty | Return cable/crossover/connectors, Keyspan RX, or driver delivery |

A standalone `15` during the intentionally bad-CRC test is the documented NAK
behavior and supports a functioning request/return exchange when correlated to
that request. ACK or a framed reply is unexpected and must be retained and
investigated, including possible delayed replies. Zero bytes is inconclusive:
it cannot distinguish request path, return path, interface, or baud problems.
The manual documents ACK for a valid addressed request and NAK for incorrect CRC.
[SICK Telegram Listing, section 4.3, p24](https://sicktoolbox.sourceforge.net/docs/sick-lms-telegram-listing.pdf).

Report Test A and B attempts, exact supplied bytes, write counts, queue/drain,
ACK/NAK/framed/partial/other/silent classifications, listener/read/raw-file evidence,
and DCB results separately from instrument data. Until a physical capture exists,
on-wire bytes, minimum/maximum electrical gaps, request presence at LMS RX,
LMS TX activity/latency, and the implicated physical segment are **unverified**.
