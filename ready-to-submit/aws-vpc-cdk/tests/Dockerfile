FROM public.ecr.aws/docker/library/node:22-bookworm-slim@sha256:f3a68cf41a855d227d1b0ab832bed9749469ef38cf4f58182fb8c893bc462383

LABEL org.opencontainers.image.title="aws-vpc-cdk-tests" \
      org.opencontainers.image.version="1.0.0"

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NODE_PATH=/usr/local/lib/node_modules \
    PATH=/usr/local/bin:/usr/bin:/bin

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        python3 \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --break-system-packages \
        pytest==8.3.5 \
        pytest-json-ctrf==0.5.3 \
        ruff==0.8.4

RUN npm install -g --no-audit --no-fund \
        aws-cdk-lib@2.155.0 \
        constructs@10.3.0

RUN mkdir -p /app/cdk-vpc /tests /logs/verifier

COPY test.sh /tests/test.sh
COPY test_outputs.py /tests/test_outputs.py
COPY fixtures/ /tests/fixtures/

RUN chmod +x /tests/test.sh

WORKDIR /tests
