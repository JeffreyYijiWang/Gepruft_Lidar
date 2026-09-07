from lms200.protocol.framing import Control, Frame, Framer


def test_every_split_and_concatenation(golden):
    raw = golden["mode_response_81"]
    for i in range(1, len(raw)):
        f = Framer()
        assert not f.feed(raw[:i])
        assert f.feed(raw[i:]) == [Frame(0x81, raw[4:-2], raw)]
    assert len(Framer().feed(raw * 3)) == 3


def test_ack_nak_noise(golden):
    f = Framer()
    events = f.feed(b"noise\x06\x15" + golden["status"])
    assert events[:2] == [Control.ACK, Control.NAK]
    assert f.stats.noise_bytes == 5
    assert isinstance(events[2], Frame)


def test_crc_and_invalid_length_recovery(golden):
    f = Framer()
    raw = golden["mode_response_81"]
    broken = raw[:-1] + bytes([raw[-1] ^ 1])
    events = f.feed(b"\x02\x81\xff\xff" + broken + raw)
    assert [e.raw for e in events if isinstance(e, Frame)] == [raw]
    assert f.stats.crc_errors == 1
    assert f.stats.invalid_lengths == 1


def test_incomplete_plausible_length_expires(golden):
    f = Framer()
    raw = golden["mode_response_81"]
    assert not f.feed(b"\x02\x81\x00\x03" + raw)
    assert any(isinstance(e, Frame) and e.raw == raw for e in f.expire())
    assert f.stats.truncated_frames == 1
