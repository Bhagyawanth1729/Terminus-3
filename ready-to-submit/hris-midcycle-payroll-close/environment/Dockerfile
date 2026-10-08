# Canonical Terminus Python base (digest-pinned).
FROM public.ecr.aws/docker/library/python:3.13-slim-bookworm@sha256:01f42367a0a94ad4bc17111776fd66e3500c1d87c15bbd6055b7371d39c124fb

LABEL org.opencontainers.image.title="hris-midcycle-payroll-close" \
      org.opencontainers.image.description="Broken HRIS mid-cycle payroll close" \
      org.opencontainers.image.version="1.0.0" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.created="2026-08-10T00:00:00Z"

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TZ=UTC \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/hris

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        asciinema \
        ca-certificates \
        tmux \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/hris

COPY hris/ /app/hris/

RUN mkdir -p /app/hris/var /app/hris/out \
    && chmod 0755 /app/hris/bin/hrctl \
    && python3 -c "import sqlite3; from pathlib import Path; con=sqlite3.connect('/app/hris/var/hris.db'); con.executescript(Path('/app/hris/sql/schema.sql').read_text()); con.executescript(Path('/app/hris/sql/seed.sql').read_text()); con.commit()"

CMD ["sleep", "infinity"]
