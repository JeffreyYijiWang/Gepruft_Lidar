"""Offline derivation from SICK Telegram Listing section 9, pp107-108.

No serial imports or hardware operations. The rolling-word form follows the
published assembler rather than calling the project's CRC implementation.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from lms200.protocol.crc import crc16

body = bytes([0x02, 0x00, 0x01, 0x00, 0x31])
signature = word = 0
trace = []
for octet in body:
    word = ((word << 8) | octet) & 0xFFFF
    carry = signature >> 15
    signature = (signature << 1) & 0xFFFF
    if carry:
        signature ^= 0x8005
    signature ^= word
    trace.append({"input": f"{octet:02X}", "crc": f"{signature:04X}"})
assert signature == 0x1215  # Published complete request, Table 7-31 p52.
assert crc16(body) == signature
packet = body + signature.to_bytes(2, "little")
assert packet == bytes.fromhex("02 00 01 00 31 15 12")
result = {
    "timestamp_utc": datetime.now(UTC).isoformat(),
    "source": "https://sicktoolbox.sourceforge.net/docs/sick-lms-telegram-listing.pdf",
    "sections": "Table 7-31 p52; section 9 pp107-108",
    "method": "offline rolling-word transcription of manufacturer algorithm",
    "trace": trace,
    "numeric_crc": f"{signature:04X}",
    "packet_hex": packet.hex(" ").upper(),
    "project_crc_matches": True,
    "hardware_opened": False,
}
output = Path(__file__).with_name("status-crc-verification.json")
with output.open("x", encoding="utf-8") as stream:
    json.dump(result, stream, indent=2)
print(json.dumps(result, indent=2))
