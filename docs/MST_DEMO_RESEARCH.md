# Original SICK MST Demo / MST 200 research

Research completed **2026-09-07 UTC (2026-09-06 EDT)** for LMS200-30106, P/N 1015850,
Keyspan USA-19HS on Windows COM7. Read `AGENTS.md` and the hardware diagnostic record first.
The operator-confirmed bare adapter loopback and failed scanner exchanges, including the
isolator bypass, remain unchanged. This task performed no serial I/O or software execution.

## Result: documented, no trustworthy software package located

**The original MST Demo ZIP was not found or downloaded.** No verified public ZIP filename,
software download URL, SDK distribution, example-source distribution, or complete-source
distribution was established. This is the result of the sources checked, not a claim that
SICK no longer holds the package. The [SICK-authored quick manual, page 20][m20] directs
readers to their local representative for the demo software and manual on request.

Only documentation, manual-page images and archive indexes were downloaded. They are stored
in the dedicated directory `third_party/sick_mst/research-20260907/`, excluded by both
`.gitignore` and `.dockerignore`. No third-party files in that directory are tracked by Git.
The directory is **not an installed or extracted MST software package**.

The original software's size, SHA-256, executable version, architecture, signatures, EULA,
and redistribution permission are unavailable. No archive was available to list, reject or
extract. No executable, DLL, installer or script from a third party was downloaded or run;
no DLL registration, driver installation, security change or administrative launch occurred.
The project's driver was not modified.

## Exact manual and page map

The requested [ManualsLib document][m1] reproduces SICK AG Auto Ident's **Quick Manual for
MST Demo setup — Software setup and configuration**, **Version 1.0, August 2002 (HW/MV)**,
20 pages. This is a different document from the repository's June 2001 *Quick Manual for
LMS communication setup*, even though their hardware sections overlap. The manual revision
is not evidence of a particular executable's version.

The [contents page][m2] and the actual linked pages establish:

| Printed / viewer page | Section or relevant content |
| --- | --- |
| 1 | Title, revision and SICK authorship |
| 2 | Contents; duplicate section number C.2 is present in the document |
| 5 | Power supply; **not** the MST installation page |
| [9][m9] | C. Communication via MST Demo; C.1 Principle of MST-Demo; C.2 Installation of MST |
| [10][m10] | C.2 Communication LMS to PC with MST; connection settings and application menu |
| [11][m11] | C.3 Record LMS scan data |
| [12][m12]–[13][m13] | C.4 Replay and C.5 recorder configuration |
| [14][m14]–17 | C.6 recorded-data conversion and output explanation; pages 14 onward identified by contents and page 14, not all conversion pages downloaded |
| [20][m20] | D.2 Further information and documentation; software supplied on request |

Page 9 describes a compiled demonstration of MST 200 functionality and a scan-recording
tool for evaluating applications. Its installation procedure is to create a dedicated
directory, unpack the supplied ZIP there, then launch `MSTDemo.exe`. It supplies **no ZIP
basename, public download link, installer command, DLL-registration command or source-code
promise**. The screenshot shows executables, DLLs and a `Configuration_LMS` folder.

## What is documented, and what is actually available

| Item | Evidence and classification | Download/inspection result |
| --- | --- | --- |
| `MSTDemo.exe` | Compiled demonstration application named on [page 9][m9] | Documented only; no binary acquired |
| MST 200 / Measurement Software Tool | SICK's [product information][brochure] calls it an SDK with libraries, communication drivers and measurement-processing functions | Product documentation acquired; SDK libraries not acquired |
| DLLs | Page 9's screenshot visibly includes LMS DLLs and `mfc42.dll` / `msvcrt.dll` runtime filenames | Screenshot evidence, **not** a verified archive inventory or import/dependency analysis; other small labels not relied upon |
| `Configuration_LMS`, `LMSRecorder.cfg` | [Page 13][m13]: presets and an editable recorder configuration | Configuration data, not program source; no actual CFG acquired |
| `LMSDATA.dat`, `LMSData.txt` | [Pages 11][m11] and [14][m14]: recorded binary data and converted text output | Data-file names, not software downloads |
| Example applications | Page 10's menu shows multiple demonstrations | A menu entry does not establish that example source accompanies the ZIP |
| Example source code | No licensed distribution located | Serial-open API, flow-control choices and initialization sequence cannot be inspected |
| Complete MST library/demo source | No distribution or source license located | Not established; an SDK or ZIP must not be described as complete source |
| *Technical Description Measurement Software Tool MST 200 for PC Version 2.0* | [Page 20][m20] gives SICK order number **8008464** | Referenced, but this technical-description document was not obtained |

The older [June 2001 communication manual, page 13][communication] describes an MST driver
library based on Visual C++ 6.00, plus the compact MSTDemo application. It does not establish
the contents or license of the missing August 2002 demo ZIP.

An independent [Universitat Politècnica de València thesis][upv], printed pages 101–102
(PDF pages 133–134), reports using **MST 200 Demo Application v2.01** supplied by SICK.
Its bibliography, printed page 105 (PDF page 137), cites the August 2002 quick manual.
This corroborates a historical demo version but supplies no verified software download.
The bibliography associates `8007954/0000/04-04-2003` with that citation; this identifier is
not verified on the quick manual itself and overlaps the telegram-listing document family,
so it is **not adopted as the MST quick manual's confirmed order number**.

## Compatibility and connection behavior

| Question | Verified evidence / remaining limitation |
| --- | --- |
| Documented Windows baseline | The SICK MST 200 product brochure, print code **8008456.0499**, page 2, lists Windows NT / Windows 95, Pentium 133 MHz and 16 MB RAM for the PC product; MS Visual C++ is the development environment. This is historical product information, not certification of the missing demo build on Windows 11. |
| 32-bit / 64-bit | No executable was obtained, so PE architecture and any installer bitness cannot be checked. The historical Windows/MFC context suggests a legacy Win32 application, but that remains an inference. Neither native 64-bit support nor Windows 11 compatibility is established. |
| Runtime dependencies | The quick-manual screenshot shows MFC/C runtime DLLs. Required versions, complete import lists, driver dependencies, .NET requirements or absence thereof, and installation prerequisites remain unverified. Visual C++ being used to develop MST does not prove the full compiler is required to run the demo. |
| COM-port selection | [Page 10][m10] shows a Port dropdown, a selected COM1, an interface-type dropdown and a baud dropdown. Its list is closed. **COM7 support is not verified.** No evidence establishes the maximum COM number or whether enumeration is dynamic. |
| Windows port assignment | COM7 remains unchanged. If a future verified version cannot select it, stop and investigate that version; do not automatically renumber the adapter. |
| Baud behavior | Page 10 specifies initial 9600 Bd but says MST automatically uses the highest available baud rate when started. Selecting 9600 is therefore **not a verified fixed-9600 policy**. Exact timing of baud negotiation and whether it persists are undocumented here. |
| Launching the EXE / accepting Options | The manual shows a start screen and then an Options dialog. It does not prove that launching the EXE or accepting the dialog sends zero bytes; no code or runtime trace was available. |
| Starting an application | [Page 11][m11] says the recorder begins displaying and saving scans after its first-use configuration message is accepted. [Page 13][m13] says recorder configuration is used by the LMS when the recorder next starts. This is a recording/configuration workflow, not a verified read-only status probe. |
| Default recorder state | Page 13 documents 180 degrees, 0.5-degree resolution and 8 m measurement range. Existing scanner settings must not be assumed to survive starting it. |

There is **no verified procedure in the obtained material for one read-only status request
at fixed 9600 with all automatic changes disabled**. A vendor demo can provide independent
evidence, but its documented behavior exceeds the previous status-only commissioning scope.
This finding does not authorize a new hardware test.

The [Comtrol manual][comtrolpdf] lists Windows 2000/XP/Server 2003/Vista for its **NS-Link
driver**. Those are not MST-specific requirements and are not applied to the Keyspan.
Its DeviceMaster, 500-kbaud, WCom2 and firmware instructions are for different hardware.

## Verified instructions to retain for a later supervised test

These describe the manual and the unresolved gates; **nothing below was executed**.

1. Obtain the original PC demo ZIP and its license from SICK or a verifiable archive. Before
   extraction, inventory the archive and reject absolute paths, drive/UNC paths, `..`
   traversal, links/reparse entries, Windows alternate-stream paths, and destinations outside
   a new empty extraction directory. Preserve the original ZIP and record its URL, date,
   byte size and SHA-256. Never extract over this repository's source files.
2. The page 9 installation method is directory extraction followed by `MSTDemo.exe` from
   that directory, preserving its layout and bundled DLLs. No additional installer,
   registration command or administrator requirement is documented. Verify the actual
   supplied README/EULA and binary dependencies before approving a launch.
3. A later supervised, hardware-disconnected UI inspection could verify the executable
   version and COM dropdown without testing the scanner. Physical disconnection and software
   execution would each require the operator's explicit instruction then. Do not infer that
   they have already happened, or weaken Windows security to make the application run.
4. The documented UI route is Options → communication parameters: sensor, port, interface
   type and initial baud. For this setup the intended selection would be COM7 and the
   standard PC serial interface, initially 9600. **Verify COM7 actually exists in that
   version; do not substitute another port or a high-speed-card profile.**
5. Stop before a connected launch, accepting connection settings, or selecting a Start
   application until the actual version's communication behavior is known. Ask SICK how to
   disable automatic baud selection and scanner configuration/streaming. If it cannot perform
   a read-only exchange, a broader supervised test requires a new explicit scope.

The manual's Start → recording application is **not** the next status-only test. Do not copy
its recorder presets, delete CFG files to reset defaults, or run the recording application
as an apparently harmless connection check.

## Sources checked, provenance and unavailable material

| Source | Result |
| --- | --- |
| [Requested ManualsLib manual][m9] | The web reader repeatedly failed on query-string pages 9/10. Direct HTTPS retrieval with curl succeeded for pages 1, 2, 9–14 and 20; page images 9–11 were visually inspected. Thus those contents were recovered, not assumed from search snippets. |
| SICK website and public search | Searches for MST Demo, MSTDemo, MST200, ZIP, SDK, examples and the exact quick-manual title found product/manual references, but no provenance-verified software archive or institutional copy of the same quick manual. No private SICK account or request-only delivery was accessed. |
| [SICK-authored MST 200 brochure hosted by AUDIN][brochure] | Identifiable industrial supplier mirror; SICK branding, contact line and printed document code. Downloaded the two-page product information and visually verified page 2. It is not the requested quick manual or the SDK. |
| [University of Hamburg TAMS laser hardware page][tams] | Identifiable university research group. Its linked `2LMS2Rabbit.zip` is code for its Rabbit/PowerCore embedded scanner interface, not SICK MST Demo. **Not downloaded or substituted.** |
| [UPV institutional thesis][upv] | Read the MST version reference and bibliography through the web reader. Research evidence, not an MST distribution. Full thesis not downloaded locally. |
| [Comtrol official legacy documentation index][comtrolindex] | Links to the vendor's original scanner-installation PDF; that PDF says SICK MST Demo was included on a DeviceMaster Software and Documentation CD. No MST ZIP link in the PDF. |
| [Comtrol DeviceMaster 500 archive][comtroldir] | Direct HTTPS directory indexes inspected, including software and Windows utility directories. The visible entries are DeviceMaster firmware/utilities, not an identified MST package. No binaries downloaded. Web reader failed on some directory/PDF URLs; direct curl retrieval succeeded. |
| [SICK official telegram listing][telegrams] | Distinguishes LMSIBS configuration software from MST200 measurement software on p17. Documentation evidence, not an MST download. |

No unidentified executable mirror, download-manager installer or cracked distribution was used.
SOPAS was not downloaded or substituted. LMSIBS is the separate legacy configuration tool;
sicktoolbox is a different driver implementation. Neither supplies the requested original demo
merely by being compatible with LMS2xx. The university's embedded source and Comtrol's
DeviceMaster SDK/firmware are also different products.

### Locally retained documentation

Base directory: `third_party/sick_mst/research-20260907/`.
Retrieval: **2026-09-07 UTC**. `retrieval-manifest.json` records each of the 22 retained
documentation/index/render assets, source URL, local completion timestamp, size and SHA-256.
The 22 assets total 4,212,183 bytes, excluding the manifest. No asset is a software archive.

| File | Provenance / available version | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| `MST200-audin.pdf` | [SICK product information / AUDIN][brochure], print code 8008456.0499; PDF metadata creation 2000-04-25, modification 2009-10-29, not software build dates | 381509 | `c1f573f6cdd447622d740fb332d43cbfdf175f85986bb1909b134ccedcdefffe` |
| `comtrol-lms-scanner-install.pdf` | [Comtrol original PDF][comtrolpdf], 2000472 Rev. C, Third Edition 2008-11-03, copyright 2007–2008 | 509910 | `c297df96eb4db6dcfd7037d3d676b22fca0c08f28d7cf1acec61ec28620c2005` |
| `manualslib-page*.html` and pages 9–11 `.jpg` | The requested SICK quick manual's rendered text/screenshots; hashes individually in the manifest | See manifest | See manifest |

The SICK quick manual carries an all-rights-reserved copyright notice. No software EULA or
permission to redistribute binaries or licensed source was obtained. The public location of
documentation does not establish a software redistribution license. Copies stay excluded
from Git and the Docker build context.

## Exact request to SICK

Use the current [SICK USA contact/support page][support], which lists **techhelp@sick.com**,
or create a request in the [SICK Support Portal][portal]. No request was sent in this task.

Suggested request:

> Please provide the original SICK MST Demo / MST 200 PC demo ZIP for an LMS200-30106,
> P/N 1015850, corresponding to the *Quick Manual for MST Demo setup — Software setup and
> configuration*, version 1.0, August 2002 (HW/MV), particularly pp9–13 and p20. The executable
> is named MSTDemo.exe. Please identify the appropriate release; historical research also
> mentions MST 200 Demo Application v2.01. Please include the README, EULA, dependency list,
> original checksum if available, and *Technical Description Measurement Software Tool MST
> 200 for PC Version 2.0*, order number 8008464. Supply SDK libraries and permitted example
> source separately if available, clearly distinguishing them from complete library source.
>
> Our Windows adapter is a Keyspan USA-19HS on COM7. Bare pin 2–3 loopback passes, but the
> scanner produces no valid startup telegram and does not answer the single binary status
> request 02 00 01 00 31 15 12 at 9600 8-N-1. This persists with and without the suspected
> opto-isolator. We want an independent vendor communication test. Please confirm COM7
> selection, supported Windows versions and 32-/64-bit constraints, required runtimes, whether
> launch/Options/Start changes the scanner or starts output, and whether automatic baud changes,
> configuration and streaming can all be disabled for a fixed-9600 read-only status check.

[m1]: https://www.manualslib.com/manual/2174386/Sick-Lms-200.html
[m2]: https://www.manualslib.com/manual/2174386/Sick-Lms-200.html?page=2
[m9]: https://www.manualslib.com/manual/2174386/Sick-Lms-200.html?page=9
[m10]: https://www.manualslib.com/manual/2174386/Sick-Lms-200.html?page=10
[m11]: https://www.manualslib.com/manual/2174386/Sick-Lms-200.html?page=11
[m12]: https://www.manualslib.com/manual/2174386/Sick-Lms-200.html?page=12
[m13]: https://www.manualslib.com/manual/2174386/Sick-Lms-200.html?page=13
[m14]: https://www.manualslib.com/manual/2174386/Sick-Lms-200.html?page=14
[m20]: https://www.manualslib.com/manual/2174386/Sick-Lms-200.html?page=20
[brochure]: https://www.audin.fr/pdf/documentations/sick/mesure-et-vision/scanners-de-mesure/MST200.pdf
[communication]: https://www.danarte.es/archivos/pdf/1866.pdf
[upv]: https://riunet.upv.es/bitstreams/e654611e-cb59-4270-9e54-097968846550/download
[tams]: https://tams.informatik.uni-hamburg.de/research/robotics/service_robot/hardware/index.php?content=laser
[comtrolindex]: https://files.comtrol.com/html/Obsolete_DM500_docs.htm
[comtroldir]: https://files.comtrol.com/obsolete/dev_mstr/500/
[comtrolpdf]: https://files.comtrol.com/obsolete/dev_mstr/500/install_docs/lms_scanner_install.pdf
[telegrams]: https://www.sick.com/media/docs/3/03/003/telegram_listing_telegrams_for_configuring_and_operating_the_lms2xx_laser_measurement_systems_en_im0015003.pdf
[support]: https://www.sick.com/us/en/contact-support/contact-sick-usa/w/contact-details
[portal]: https://support.sick.com/
