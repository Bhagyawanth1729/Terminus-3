FROM public.ecr.aws/docker/library/python:3.13-slim-bookworm@sha256:01f42367a0a94ad4bc17111776fd66e3500c1d87c15bbd6055b7371d39c124fb

LABEL org.opencontainers.image.title="jetstream-regional-stream-continuity-verifier" \
      org.opencontainers.image.version="2.0.0" \
      org.opencontainers.image.licenses="Apache-2.0"

ARG NATS_SERVER_VERSION=2.14.3
ARG NATS_SERVER_DEB_SHA256=e0c053fc2abe991f17b2be794897bb3f94ca1857bf886498c741ba69fb62522a

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        sqlite3 \
        curl \
        ca-certificates \
        procps \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL -o /tmp/nats-server.deb "https://github.com/nats-io/nats-server/releases/download/v${NATS_SERVER_VERSION}/nats-server-v${NATS_SERVER_VERSION}-amd64.deb" \
    && echo "${NATS_SERVER_DEB_SHA256}  /tmp/nats-server.deb" | sha256sum -c - \
    && dpkg -i /tmp/nats-server.deb \
    && rm -f /tmp/nats-server.deb

COPY requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir -r /tmp/requirements.lock \
    && rm -f /tmp/requirements.lock

RUN mkdir -p /app/continuity
COPY test.sh test_outputs.py /tests/
RUN chmod 0755 /tests/test.sh

WORKDIR /app/continuity
