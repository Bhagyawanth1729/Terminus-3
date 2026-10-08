# Debian is the canonical Terminus base and no dedicated GnuCOBOL image is
# sanctioned. The compiler and PostgreSQL ESQL toolchain are required because
# agents rebuild the native application in place.
FROM public.ecr.aws/docker/library/debian:bookworm-slim@sha256:4724b8cc51e33e398f0e2e15e18d5ec2851ff0c2280647e1310bc1642182655d AS toolchain

LABEL org.opencontainers.image.title="claims-terminal" \
      org.opencontainers.image.version="1.0.0" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.created="2026-08-02T00:00:00Z"

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    OCESQL_COMMIT=14591d82b6423ed76540ced70f1d4752d31882f3 \
    OCESQL_SHA256=28a331b2e2fa2c41ed90ef751416254579145cdbdf6a977983b6e33dcbe41145 \
    COBCPY=/usr/local/share/ocesql/copy:/app/claims/src/copybooks \
    LD_LIBRARY_PATH=/usr/local/lib \
    PATH=/app/claims/bin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        asciinema \
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
        postgresql-client \
        tmux \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL -o /tmp/ocesql.tar.gz \
        "https://github.com/opensourcecobol/Open-COBOL-ESQL/archive/${OCESQL_COMMIT}.tar.gz" \
    && echo "${OCESQL_SHA256}  /tmp/ocesql.tar.gz" | sha256sum -c - \
    && mkdir -p /tmp/ocesql \
    && tar -xzf /tmp/ocesql.tar.gz --strip-components=1 -C /tmp/ocesql \
    && cd /tmp/ocesql \
    && autoreconf -fi \
    && CPPFLAGS="-I/usr/include/postgresql" ./configure --prefix=/usr/local \
    && make -j2 \
    && make install \
    && ldconfig \
    && rm -rf /tmp/ocesql /tmp/ocesql.tar.gz

FROM toolchain AS task

WORKDIR /app/claims

COPY docs/ /app/claims/docs/
COPY db/schema.sql /app/claims/db/schema.sql
COPY src/ /app/claims/src/
COPY bin/ /app/claims/bin/
COPY Makefile /app/claims/Makefile

RUN chmod 0755 /app/claims/bin/build-claims /app/claims/bin/claimsctl \
    && mkdir -p /app/claims/build \
    && /app/claims/bin/build-claims

CMD ["sleep", "infinity"]
