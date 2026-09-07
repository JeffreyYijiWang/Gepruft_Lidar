"""All synthetic response fixtures are generated from the documented layout, not captures."""

import json
from pathlib import Path

import pytest


@pytest.fixture
def golden():
    data = json.loads((Path(__file__).parent / "fixtures/golden.json").read_text())
    return {k: bytes.fromhex(v) for k, v in data.items() if k != "provenance"}
