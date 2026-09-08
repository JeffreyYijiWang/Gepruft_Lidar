"""Offline archive guards and capture preservation; no third-party code is required."""

import io
import json
import zipfile

import pytest

from lms200 import lmsapi_check as check
from lms200.protocol.crc import crc16


@pytest.mark.parametrize(
    "entry", ["../outside.c", "/lmsapi/a.c", "lmsapi/../a.c", "C:/lmsapi/a.c", "lmsapi/a.c:stream"]
)
def test_archive_rejects_unsafe_names(entry):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(entry, b"unused")
    with zipfile.ZipFile(buffer) as archive, pytest.raises(ValueError, match="Unsafe"):
        check.inspect_archive(archive)


def test_archive_rejects_windows_case_collision():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("lmsapi/a.c", b"first")
        archive.writestr("lmsapi/A.c", b"second")
    with zipfile.ZipFile(buffer) as archive, pytest.raises(ValueError, match="duplicate"):
        check.inspect_archive(archive)


def test_unreviewed_archive_does_not_build_or_create_directory(tmp_path, monkeypatch):
    package = tmp_path / "unreviewed.zip"
    package.write_bytes(b"unreviewed bytes")
    workdir = tmp_path / "build"

    def forbidden(*args, **kwargs):
        pytest.fail("Compiler must never execute for unreviewed source")

    monkeypatch.setattr(check.subprocess, "run", forbidden)
    with pytest.raises(ValueError, match="differs"):
        check.run(package, workdir, "gcc", [])
    assert not workdir.exists()


def test_capture_preserves_noise_and_separates_runs_and_phases(tmp_path):
    frame = check.GOLDEN["manual_startup"]
    records = [
        ("first", "passive", b"\xf0\x39\x14\x31\x21\x31\x01"),
        ("first", "status", b"\x06" + frame[:8]),
        ("first", "status", frame[8:]),
        ("second", "passive", frame[:-1] + bytes([frame[-1] ^ 1])),
    ]
    path = tmp_path / "capture.jsonl"
    text = "\n".join(
        json.dumps({"event": "rx", "run_id": run, "phase": phase, "hex": data.hex()})
        for run, phase, data in records
    )
    path.write_text(text)
    result = check.check_capture(path, crc16)
    streams = result["streams"]
    assert streams[0]["rx_bytes"] == 7 and streams[0]["valid_frames"] == 0
    assert streams[0]["complete_candidates"] == []  # No STX means no CRC pass.
    assert streams[1]["valid_frames"] == 1
    assert streams[1]["complete_candidates"][0]["offset"] == 1
    assert streams[2]["valid_frames"] == 0
    assert streams[2]["complete_candidates"][0]["crc_valid"] is False
    assert path.read_text() == text


def test_comparison_detects_wrong_crc_implementation():
    result = check.compare(lambda data: crc16(data) ^ 1)
    assert not result["passed"]
    assert all(not item["match"] for item in result["published"])
    assert len(result["synthetic_mismatch_indices"]) == result["synthetic_vectors"]
