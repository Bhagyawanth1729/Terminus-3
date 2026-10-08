# Debian slim is required as the final runtime because the lab runs digest-pinned
# nats-server 2.14.3 alongside SQLite and the Python control plane; the canonical
# language images do not ship that JetStream binary.
FROM public.ecr.aws/docker/library/debian:bookworm-slim@sha256:4724b8cc51e33e398f0e2e15e18d5ec2851ff0c2280647e1310bc1642182655d

LABEL org.opencontainers.image.title="Regional JetStream continuity service"
LABEL org.opencontainers.image.version="1.0"

ARG NATS_SERVER_VERSION=2.14.3
ARG NATS_SERVER_DEB_SHA256=e0c053fc2abe991f17b2be794897bb3f94ca1857bf886498c741ba69fb62522a

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 \
      python3-venv \
      python3-pip \
      sqlite3 \
      curl \
      ca-certificates \
      tmux \
      asciinema \
      jq \
      procps \
      patch \
 && rm -rf /var/lib/apt/lists/* \
 && curl -fsSL -o /tmp/nats-server.deb "https://github.com/nats-io/nats-server/releases/download/v${NATS_SERVER_VERSION}/nats-server-v${NATS_SERVER_VERSION}-amd64.deb" \
 && echo "${NATS_SERVER_DEB_SHA256}  /tmp/nats-server.deb" | sha256sum -c - \
 && dpkg -i /tmp/nats-server.deb \
 && rm -f /tmp/nats-server.deb

WORKDIR /app/continuity
COPY continuity/ /app/continuity/

RUN python3 -m venv /opt/continuity-venv \
 && /opt/continuity-venv/bin/pip install --no-cache-dir --upgrade "pip==25.2" \
 && /opt/continuity-venv/bin/pip install --no-cache-dir "nats-py==2.15.0" \
 && mkdir -p /app/continuity/state /app/continuity/out /app/continuity/run /app/continuity/log/runtime \
 && chmod +x /app/continuity/bin/* \
 && sqlite3 /app/continuity/state/continuity.db < /app/continuity/sql/schema.sql \
 && sqlite3 /app/continuity/state/continuity.db < /app/continuity/sql/runtime_extensions.sql \
 && sqlite3 /app/continuity/state/continuity.db < /app/continuity/sql/seed.sql

ENV PATH="/opt/continuity-venv/bin:${PATH}"
ENV PYTHONPATH="/app/continuity"
ENV CONTINUITY_ROOT="/app/continuity"
