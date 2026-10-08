FROM public.ecr.aws/docker/library/golang:1.24-bookworm@sha256:1a6d4452c65dea36aac2e2d606b01b4a029ec90cc1ae53890540ce6173ea77ac

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GOTOOLCHAIN=local

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl jq python3 python3-pip procps \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m pip install --break-system-packages --no-cache-dir pytest==8.4.1

RUN mkdir -p /app/edge-router /logs/verifier /tests
COPY . /tests/
RUN chmod 0755 /tests/test.sh
WORKDIR /app
