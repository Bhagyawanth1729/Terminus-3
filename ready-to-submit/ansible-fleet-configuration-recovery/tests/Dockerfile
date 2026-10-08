# Separate verifier image for environment_mode=separate.
FROM public.ecr.aws/docker/library/python:3.13-slim-bookworm@sha256:01f42367a0a94ad4bc17111776fd66e3500c1d87c15bbd6055b7371d39c124fb

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TZ=UTC \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir -r /tmp/requirements.lock \
    && rm -f /tmp/requirements.lock

RUN mkdir -p /tests /logs/verifier
COPY test.sh test_fleet_recovery.py /tests/
RUN chmod 0755 /tests/test.sh
WORKDIR /tests
