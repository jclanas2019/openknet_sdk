# ---- builder ----
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY openknet/ openknet/
COPY README.md .

RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -e .


# ---- runtime ----
FROM python:3.12-slim AS runtime

WORKDIR /app

# Copy installed packages and entrypoint
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/openknet /usr/local/bin/openknet
COPY --from=builder /build /app

# Non-root user
RUN useradd -m openknet
RUN mkdir -p /data && chown openknet:openknet /data
USER openknet

ENV OPENKNET_WORKSPACE_ROOT=/data
ENV OPENKNET_LOG_LEVEL=INFO

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["openknet", "serve", "--host", "0.0.0.0", "--port", "8000"]
