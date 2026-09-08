# ADR 0002: Transparent data channel and separate leased control channel

Accepted 2026-09-06. Native Python owns the physical serial adapter on Windows/macOS.
TCP data remains byte-for-byte transparent; a separate JSON-lines control connection
authenticates, leases a single data session, and changes host baud. Data sockets are paired
to the lease via a dedicated listener returned by control (7000 by default, ephemeral when
configured as port 0). No token or JSON
is injected into LMS bytes. Control and data must have the same peer IP.

Receive ACK and the entire A0 at the old baud, then change the adapter through the control
channel and verify with status. No automatic repeat of an ambiguous baud change. Detection
starts at 9600, then 38400, then 19200 (also documented), with 500000 only on explicit opt-in.
Uncontrolled third-party transparent bridges support fixed baud only; detection and switching
cannot change the adapter without a control channel.

500000 is an explicit RS-422 mode, with host-side command-byte pacing to meet the listing's
minimum 55 us between bytes. Ordinary operating systems and USB adapters cannot guarantee
the 6 ms upper bound under load: software tests cover scheduling/control, physical timing
and high-rate reliability require a logic analyzer and real adapter qualification.

Bridge binds loopback by default. Docker Desktop access needs a reachable host interface,
a token, and a host firewall allowing only the local container environment. No TLS: trusted
local network or an encrypted tunnel only. No privileged containers or host-driver claims.
