# Hardware connection — LMS200-30106, 1015850

Sources: [SICK data sheet](https://www.sick.com/media/pdf/3/43/843/dataSheet_LMS200-30106_1015850_es.pdf)
pp2–4, [Quick Manual](https://www.danarte.es/archivos/pdf/1866.pdf) §B pp4–8 and §C.2 p9,
[2008 technical supplement](https://www.sick.com/media/docs/3/33/933/technical_information_lms200_211_221_291_laser_measurement_systems_en_im0027933.pdf)
§1.1 p3. The supplement takes precedence over older data connector diagrams.

## Power and connectors

Use a regulated 24 V DC supply (±15%) rated for at least 2.5 A. Typical consumption is
30 W; account for cable voltage drop and startup. Provide suitable current limiting/fusing
and the correct LMS200 connector or cable. The device is discontinued, indoor-rated,
IP65 with correctly assembled connectors, and specified for 0–50°C. It uses a 905 nm
Class 1 laser. It is not a certified machine-safety protective device.

The power/I/O connector and the serial data connector are **different connectors with the
same pin count**. Identify them from the housing/manual, not shape alone. USB-C alone is
insufficient. Never send 24 V into the data connector, computer, USB port, or serial adapter.

For the LMS200 power/I/O connector only, Quick Manual §B.2.a p5 specifies pin 1 = supply
ground and pin 3 = +24 V. Pin 2 is restart input; 5/8/9 are outputs, not serial data;
4/6/7 are unconnected. Check connector viewing direction and molded pin numbers before
wiring; these power pin numbers must never be applied to the data connector.

## Corrected scanner-side serial data pinout

| Pin | RS-232 | RS-422 |
| --- | --- | --- |
| 1 | Unconnected | RD− |
| 2 | RxD | RD+ |
| 3 | TxD | TD+ |
| 4 | Unconnected | TD− |
| 5 | Ground | Ground |
| 6 | Unconnected | Unconnected |
| 7 | Open | Bridge to 8 |
| 8 | Open | Bridge to 7 |
| 9 | Unconnected | Unconnected |
| Housing | Shield | Shield |

The supplement explicitly corrects pins 3 and 4 in the older Technical Description.
Quick Manual p8 also shows the obsolete RS-422 assignment, so its numeric crossover
must not be copied verbatim. Pin numbers are scanner-side connector numbers.

## RS-232 cable

Quick Manual §B.3.a p7 explicitly calls for pins 2 and 3 crossed. With a conventional
PC/DTE DB9 adapter (verify its own documentation):

| Scanner data connector | Adapter |
| --- | --- |
| 2 RxD | 3 TxD |
| 3 TxD | 2 RxD |
| 5 GND | 5 GND |
| 7, 8 | Leave open on scanner |

Use an adapter with genuine RS-232 signal levels, not TTL UART. Default is 9600 baud,
8 data bits, no parity, 1 stop bit, no software or hardware flow control. 19200 and 38400
are supported. The quick manual quotes up to 10 m for RS-232; qualify the actual cable.

## RS-422 cable

Use full-duplex, four-wire RS-422. A two-wire RS-485 auto-direction adapter is not equivalent.
The adapter must document differential polarity, host driver support, and its actual baud rates.

| Scanner data connector | Adapter signal |
| --- | --- |
| 1 RD− | TX− |
| 2 RD+ | TX+ |
| 3 TD+ | RX+ |
| 4 TD− | RX− |
| 5 GND | Signal reference according to adapter documentation |
| 7–8 | Bridge together on scanner side to enable RS-422 |

Use twisted pairs, TX with TX and RX with RX. RS-422 adapter connector numbering and A/B
labels are not universal; use the manufacturer's signal polarity definition. The corrected
scanner signal table plus transmit-to-receive crossover establishes the table above.
Check termination, reference ground, shielding, cable length, and isolation against the
adapter documentation. Do not treat the old manual's maximum cable length as a guarantee
of 500-kbaud operation on an arbitrary installation.

Prefer an adapter with stable drivers, buffering, explicit 38400/500000 support, appropriate
isolation where needed, and measurable transmit timing. Docker cannot install its host driver.
High speed is a separately enabled mode; test physical baud accuracy and inter-byte timing
before depending on it. No adapter brand or untested USB chip is endorsed by this project.

## Connection and startup order

1. Leave scanner power off. Secure the scanner and identify both connectors.
2. Verify the supply output and polarity separately. Identify data pins by molded numbering.
3. Select RS-232 or RS-422, verify cable continuity/crossover/voltage levels, and set the
   scanner 7–8 jumper only for RS-422.
4. Install the adapter's Windows/Linux/macOS host driver. Connect adapter and data cable.
5. Connect the correct power cable and apply external power. Software never energizes hardware.
6. Quick Manual p9: red and yellow during initialization; only green or only red when ready.
   Telegram Listing §7.3 p38 allows up to 60 seconds for LMS200 startup. A red field LED
   alone is not a definitive serial failure.
7. Probe at documented rates. Verify reported LMS200-30106 ID before configuration.
8. Confirm the application's four hardware checks and the RS-422 bridge check when applicable.
9. Stream/record. Stop and wait for a confirmed `20/25` reply before disconnecting.

No output wiring or field monitoring is configured by this application. Existing thresholds,
field settings, and unrelated bytes are preserved. Entering installation mode can block
switching outputs (Telegram Listing p40); this application is not a protective system.

## Checks when communication fails

Check startup LEDs, supply under load, selected host port, exclusive ownership of the port,
driver, interface voltage standard, scanner 7–8 jumper, signal crossover, polarity, ground,
and cable continuity. Use a read-only probe before writes. Do not experiment with power on
unknown pins. Additional platform and protocol checks are in [Troubleshooting](TROUBLESHOOTING.md).
