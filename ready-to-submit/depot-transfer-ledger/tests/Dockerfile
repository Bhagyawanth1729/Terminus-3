# Separate verifier: Python + pytest. Grades the agent's built binary and
# /app/output reports; does not recompile COBOL. libcob4 is the GnuCOBOL
# runtime shared library required to exec the agent-built binary (no cobc).
FROM public.ecr.aws/docker/library/python:3.13-slim-bookworm@sha256:01f42367a0a94ad4bc17111776fd66e3500c1d87c15bbd6055b7371d39c124fb

LABEL org.opencontainers.image.title="depot-transfer-ledger-verifier" \
      org.opencontainers.image.version="1.0.0" \
      org.opencontainers.image.licenses="MIT"

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TZ=UTC \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        libcob4 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    pytest==8.4.1 \
    pytest-json-ctrf==0.3.5

# Parent directories for every declared artifact path plus the reward location.
RUN mkdir -p /app /app/x /app/output /logs/verifier /tests

# Separate-verifier mode skips host upload of tests/; bake them into the image.
COPY test.sh test_outputs.py reference_ledger.py /tests/
COPY fixtures/ /tests/fixtures/
RUN chmod 0755 /tests/test.sh

WORKDIR /app
