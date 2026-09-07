#!/bin/sh
set -eu
python -m ruff format --check src tests tools
python -m ruff check src tests tools
python -m mypy
python -m pytest -q
if [ "${LMS_VERIFY_DOCKER:-0}" = "1" ]; then
    docker build --target test -t gepruft-lms200:test .
    docker build --target runtime -t gepruft-lms200:local .
fi
