# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder
WORKDIR /build
COPY pyproject.toml README.md requirements.lock ./
COPY src ./src
RUN python -m pip wheel --no-cache-dir --constraint requirements.lock --wheel-dir /wheels .

FROM builder AS test
COPY tests ./tests
COPY tools ./tools
RUN python -m pip install --no-cache-dir --constraint requirements.lock '.[dev]'
RUN ruff check src tests tools && ruff format --check src tests tools && mypy && pytest -q

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    LMS_RECORDING_DIR=/data/recordings LMS_WEB_HOST=0.0.0.0 LMS_WEB_PORT=8000
RUN groupadd --gid 10001 scanner && useradd --uid 10001 --gid scanner --create-home scanner \
    && mkdir -p /data/recordings && chown scanner:scanner /data/recordings
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels lms200 \
    && rm -rf /wheels
USER 10001:10001
WORKDIR /home/scanner
EXPOSE 8000
VOLUME ["/data/recordings"]
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
STOPSIGNAL SIGTERM
ENTRYPOINT ["lms200"]
CMD ["serve"]
