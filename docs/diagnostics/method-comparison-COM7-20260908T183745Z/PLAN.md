# Sequential method comparison, 2026-09-08

Operator requested multiple existing methods, an open listener, and angle/other
operations with the scanner ON. After reviewing the available methods, the
operator selected: "Compare Python, C++, and ROS 2 sequentially; include the gated
100°/1° sequence". The reply to the startup/current-wiring/closed-applications
prompt was exactly "green". Earlier explicit confirmations established direct
Keyspan→gray cable→LMS200 RS-232, black adapter absent, normal connector fit,
no jumpers/open scanner pins 7–8 and competing COM7 programs closed. No new wiring
or power change was requested or inferred.

Native Windows COM7 remains fixed at 9600/8-N-1 without flow control. The methods
run sequentially with exclusive ownership: each retains its handle for its entire
test, then closes before the next owner opens. This does not keep one physical
handle open across all three backends.

1. Normal Python diagnostic: one seven-byte binary status request and at least
   five seconds of post-flush reception on the same handle.
2. Direct Win32 C++: separate ReadFile worker remains armed through writes and
   drain. At most three wholly silent status attempts, each with a five-second
   reply window. Only successful ACK plus a valid B1 in supported mode 25 permits
   one 100°/1° variant, then confirmed continuous output for ten seconds and stop.
   Each step requires the matching validated response. No blind mutations.
3. Guarded ROS 2/SickToolbox harness through Windows: one status, with both readers
   ready before TX. An explicit already-powered-on mode is prepared for this
   comparison; it must not fabricate OFF/power-on/startup marker files. Windows
   receives at least five seconds after flush; ROS 2 receives six seconds.

The native angle change, if accepted, is not automatically restored. A software
reset, fault-memory clearing, baud changes, field/laser commands and arbitrary
operations are outside this selected sequence. Original LMSAPI, unmodified ROS 2
scanning-node initialization and unavailable MST Demo are not part of the selected
three-method comparison. Raw-before-parser logging, binary write counts, drain,
standalone ACK/NAK, frame lengths and CRC results are preserved separately.

Preparation: 68 focused Python tests passed before the ROS 2 powered-on addition.
Native build completed with 36 protocol, 25 sequence/handshake and 15 serial
observation checks (76 total), without opening a serial port. Live results and
final ROS 2 validation will be recorded separately; this plan claims no live outcome.
