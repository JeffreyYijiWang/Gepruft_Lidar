"""LMS2xx CRC: Telegram Listing §9, p107 (not CRC-16/IBM or Modbus)."""


def crc16(data: bytes | bytearray) -> int:
    """One shift per byte, XOR previous/current word; init=0, no final XOR."""
    result = previous = 0
    for current in data:
        result = ((result << 1) ^ (0x8005 if result & 0x8000 else 0)) & 0xFFFF
        result ^= (previous << 8) | current
        previous = current
    return result
