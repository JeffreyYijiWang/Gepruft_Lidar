"""Guards and interpretation for the isolated backend; never opens physical hardware."""

import pytest

from lms200 import lmsapi_experiment as exp
from lms200.lmsapi_check import GOLDEN
from lms200.transports.simulator import SimulatorTransport


@pytest.mark.parametrize("physical,allow", [(False, False), (False, True), (True, False)])
def test_no_helper_without_both_confirmations(tmp_path, monkeypatch, physical, allow):
    def forbidden(*args, **kwargs):
        pytest.fail("No helper execution before both confirmations")

    monkeypatch.setattr(exp.subprocess, "Popen", forbidden)
    with pytest.raises(ValueError, match="confirmation"):
        exp.run(tmp_path, tmp_path / "log", [], physical=physical, allow_legacy=allow)


def test_old_confirmation_and_duplicate_paths_are_rejected(tmp_path):
    markers = [tmp_path / name for name in ("on", "complete", "cancel")]
    markers[0].touch()
    with pytest.raises(ValueError, match="new"):
        exp.validate_markers(markers, tmp_path / "log")
    with pytest.raises(ValueError, match="differ"):
        exp.validate_markers([markers[1], markers[1], markers[2]], tmp_path / "log")


def test_failure_does_not_invent_io_counts_or_success_from_noise():
    report = exp.summarize(
        [
            {"event": "rx", "phase": "passive", "hex": "F0 39 14 31 21 31 01"},
            {"event": "connect_result", "connection_nonnull": False},
        ],
        3,
    )
    assert report["passive_rx_bytes"] == 7
    assert report["passive_valid_frames"] == []
    assert report["active_tx_bytes"] is None
    assert report["active_rx_wire_bytes"] is None
    assert not report["library_status_succeeded"]
    assert report["standalone_ack"] is None


def test_status_decode_is_separate_from_unavailable_wire_evidence():
    payload = b"\xb1" + SimulatorTransport().status_data() + b"\x10"  # Synthetic.
    report = exp.summarize(
        [
            {"event": "connect_result", "connection_nonnull": True},
            {"event": "status_result", "library_success": True, "payload_hex": payload.hex()},
            {"event": "rx", "phase": "passive", "hex": GOLDEN["manual_startup"][:7].hex()},
            {"event": "rx", "phase": "passive", "hex": GOLDEN["manual_startup"][7:].hex()},
        ],
        0,
    )
    assert report["library_status_succeeded"]
    assert len(report["passive_valid_frames"]) == 1
    assert report["status_decoded"]["baud"] == 9600
    assert report["independently_captured_active_crc"] is None
    assert report["standalone_ack"] is None


@pytest.mark.parametrize("code,payload", [(124, "B1 10"), (0, "B1 10"), (0, "A0 00 10")])
def test_unknown_status_or_crashed_helper_is_not_success(code, payload):
    report = exp.summarize(
        [
            {"event": "status_result", "library_success": True, "payload_hex": payload},
        ],
        code,
    )
    assert not report["library_status_succeeded"]
    assert report["status_decode_error"]


def test_unreviewed_zip_is_not_executed(tmp_path):
    archive = tmp_path / "different.zip"
    archive.write_bytes(b"Not the inspected package")
    with pytest.raises(ValueError, match="Unreviewed"):
        exp.prepare(archive, tmp_path / "build")
    assert not (tmp_path / "build").exists()
