FROM public.ecr.aws/docker/library/python:3.13-slim-bookworm@sha256:01f42367a0a94ad4bc17111776fd66e3500c1d87c15bbd6055b7371d39c124fb

LABEL org.opencontainers.image.title="claims-terminal-verifier" \
      org.opencontainers.image.version="1.0.0" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.created="2026-08-02T00:00:00Z"

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        autoconf \
        automake \
        bison \
        build-essential \
        ca-certificates \
        curl \
        flex \
        gnucobol \
        libpq-dev \
        libtool \
        make \
        pkg-config \
        postgresql \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL -o /tmp/ocesql.tar.gz \
        "https://github.com/opensourcecobol/Open-COBOL-ESQL/archive/14591d82b6423ed76540ced70f1d4752d31882f3.tar.gz" \
    && echo "28a331b2e2fa2c41ed90ef751416254579145cdbdf6a977983b6e33dcbe41145  /tmp/ocesql.tar.gz" | sha256sum -c - \
    && mkdir -p /tmp/ocesql \
    && tar -xzf /tmp/ocesql.tar.gz --strip-components=1 -C /tmp/ocesql \
    && cd /tmp/ocesql \
    && autoreconf -fi \
    && CPPFLAGS="-I/usr/include/postgresql" ./configure --prefix=/usr/local \
    && make -j2 \
    && make install \
    && ldconfig \
    && rm -rf /tmp/ocesql /tmp/ocesql.tar.gz

RUN pip install --no-cache-dir --no-deps \
    iniconfig==2.3.0 \
    packaging==26.2 \
    pluggy==1.6.0 \
    psycopg==3.2.9 \
    psycopg-binary==3.2.9 \
    pygments==2.20.0 \
    pytest==8.4.1 \
    pytest-json-ctrf==0.3.5 \
    ruff==0.12.7

RUN mkdir -p /app/claims /logs/verifier /tests

# Harbor's separate-verifier mode does not upload tests from the host. They are
# safe to bake here because this image is never exposed to the agent.
COPY conftest.py test_outputs.py test_concurrency.py test_benefits.py test_protocol.py \
     test_transactions.py test.sh /tests/
RUN chmod 0755 /tests/test.sh

WORKDIR /app/claims
