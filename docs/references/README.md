# Reference index and provenance

Accessed **2026-09-06**. PDFs were read locally, with visual inspection of the corrected
connector and angular-origin diagrams and status table. Reference PDFs are not redistributed;
temporary downloads are ignored by Git and Docker. Hardware/protocol facts, identifiers,
short test vectors, source links, and hashes are retained. Project licensing does not license
the vendor manuals.

| Document / publisher | URL | Used sections and facts |
| --- | --- | --- |
| LMS200-30106 product data sheet / SICK AG | [Data sheet](https://www.sick.com/media/pdf/3/43/843/dataSheet_LMS200-30106_1015850_es.pdf) | pp2–4: 1015850, model, external supply, consumption, 905 nm, Class 1, 75 Hz, range, errors, environment, discontinued/non-safety status |
| Technical Information LMS200/211/221/291, supplement 8012678/SG26, 2008-09-09 / SICK AG | [Technical supplement](https://www.sick.com/media/docs/3/33/933/technical_information_lms200_211_221_291_laser_measurement_systems_en_im0027933.pdf) | §1.1 p3, Table 1-1: corrected LMS200/LMS291 data connector pins 3 and 4, RS-422 selection bridge 7–8 |
| Quick Manual for LMS communication setup, v1.0 June 2001 / SICK AG, hosted by Danarte | [Communication setup](https://www.danarte.es/archivos/pdf/1866.pdf) | B.1 p4 power minimum/adapter; B.2 p5 power connector; B.3 pp7–8 serial crossover; C.2 p9 LEDs/startup/status; C.4 p10 baud; C.5 pp10–11 geometry; C.6 pp11–12 mode/config timing; C.7 p12 start; C.9 p14 stop; D.2 p17 high speed |
| Telegram Listing LMS2xx, 8007954/Q501, 2006-08-01 / SICK AG, hosted by SICK Toolbox | [Telegram listing](https://sicktoolbox.sourceforge.net/docs/sick-lms-telegram-listing.pdf) | §3.4 pp19–20 scans/distance coding; §4 pp21–25 framing/timing/EPROM; §7.3 pp38–39 reset/error responses; §7.4 pp40–45 modes/password/baud; §7.5 pp47–51 B0; §7.6 pp52–57 status; §7.15 p65 ID; §7.16 p66 variant; §7.43 p90 config read; §7.46 pp96–102 config write; §8 p106 status; §9 p107 CRC; §10.6–8 p124 addresses/overflows |

An additional primary implementation source was consulted to resolve the B1 length
discrepancy: [SICK Toolbox / ROS Drivers, SickLMS2xx.cc](https://github.com/ros-drivers/sicktoolbox/blob/master/c%2B%2B/drivers/lms2xx/sicklms2xx/SickLMS2xx.cc),
`_getSickStatus`, accessed 2026-09-06. No source code is copied into this project. The
source corroborates offsets; physical validation remains required.

## Corrections and precedence

1. **Data pins 3/4:** 2008 supplement takes precedence. Older Quick Manual p8's numeric
   RS-422 crossover is inconsistent. Documentation crosses signals using corrected polarity.
2. **Part number:** TL pp17/123 associate LMS200-30106 with 1017561; the requested product
   label, model-specific data sheet, and Quick Manual p4 identify target 1015850. This project
   preserves the user's exact model/part and does not generalize the older table entry.
3. **Reserved mode:** QM pp11–12 canned measurement config uses `0D`; TL p98 marks it
   reserved. The implementation uses mode `02`, a defined 13-bit distance/field mode.
4. **Units and angles:** TL p50/p124 tables contain scale inconsistencies, while §7.46 block E
   p98 explicitly defines 00=cm and 01=mm. Those definitions and B0 unit bits control decoding.
   TL p47 prose says 361 values reach 360°; 180°/0.5° counts and p48 diagrams establish 180°.
   Its 100° example omits the first 0°; QM p10 establishes 401 points including endpoints.
5. **B1 size:** the TL block-width table totals 146 bytes; the complete example specifies
   152. SICK Toolbox corroborates six reserved bytes before block E. Both exact layouts are
   documented and tested; no offset search or guessed firmware parsing is used.
6. **Configuration size:** QM config examples use 32 bytes; TL p102 uses 34, including A4.
   TL p90's textual byte count conflicts with its length field. Read length is validated and
   preserved; the driver never blindly sends the older zero-filled example.
7. **F7 success:** QM examples show 00, conflicting with TL p102's explicit 01=accepted,
   00=rejected. The explicit TL result definition wins. Firmware returning the older convention
   will fail closed and needs capture/vendor verification before adding a profile.
8. **A0 error:** TL p45 repeats result 01 for password and fault; the driver reports generic
   mode rejection rather than inventing result meanings. B1 p57 likewise repeats the laser
   state byte; laser state is not inferred.
9. **Reply address:** TL examples use 80; QM uses 81 for broadcast requests. Both are
   accepted only with broadcast addressing; individual requests require the matching address.
10. **Maximum telegram:** TL p22 says 812, while p49 adds two optional indices. The standard
    401-point case with indices is 814 bytes; this is an explicit arithmetic extension, tested.
11. **Power-up baud:** QM says it resets to 9600. TL p56 also documents a retained-baud flag.
    Detection starts at 9600 then tries other permitted rates, without changing that flag.
12. **Scan rate:** the Quick Manual's broad 75-scan wording omits multi-rotation assembly.
    TL p19 specifies two/four rotations for 0.5°/0.25°. Serial limits and actual arrivals are separate.

## Download hashes (SHA-256)

| PDF | SHA-256 |
| --- | --- |
| Data sheet | `306b7117cdd915079340b74aba1c846789f8688a8a96ec290eabf584f693c852` |
| Supplement | `486c2ca62a4b97830e8f5cf5ae3e511439962bb0a6d04b23f63c20537bc0fc72` |
| Quick Manual | `8d33cf99fdc1993b9f755ceb80c1c3ca2630e3a3f2cb5dd4a39225c6960c8d17` |
| Telegram Listing | `4feb476f16b054315bafef9df2f058b2630fee3ffc44f351fd18454e1ffe05e2` |
