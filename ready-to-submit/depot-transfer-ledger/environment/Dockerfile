# Canonical Python base. GnuCOBOL has no dedicated canonical image; Debian's
# gnucobol package supplies the compiler the agent needs on top of the sanctioned
# Python runtime used elsewhere in Terminus 3.
FROM public.ecr.aws/docker/library/python:3.13-slim-bookworm@sha256:01f42367a0a94ad4bc17111776fd66e3500c1d87c15bbd6055b7371d39c124fb

LABEL org.opencontainers.image.title="depot-transfer-ledger" \
      org.opencontainers.image.description="Broken GnuCOBOL depot transfer ledger fragments for Terminus 3." \
      org.opencontainers.image.version="1.0.0" \
      org.opencontainers.image.licenses="MIT"

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TZ=UTC \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app/x

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        asciinema \
        gnucobol \
        make \
        tmux \
    && rm -rf /var/lib/apt/lists/*

COPY . /app/x

RUN mkdir -p /app/x/bin /app/x/build /app/output \
    && cp /app/x/launcher/entry /app/x/bin/depot-ledger \
    && chmod 0755 /app/x/bin/depot-ledger /app/x/launcher/entry \
    && make clean all

WORKDIR /app/x
