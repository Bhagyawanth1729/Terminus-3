FROM ubuntu:22.04@sha256:67210e80568e6a205a2e5d95d10d1fcfdca298f24446c59b20b22a0a2df33eb8

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        gcc \
        g++ \
        golang-go \
        make \
        pkg-config \
        python3 \
        python3-dev \
        python3-pip \
        python3-venv \
        rustc \
        cargo \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /venv \
    && /venv/bin/pip install --no-cache-dir \
        pytest==8.1.1 \
        pytest-json-ctrf==0.1.7 \
        numpy==1.26.4 \
        scipy==1.12.0

RUN useradd --system --uid 12000 --user-group --no-create-home --shell /usr/sbin/nologin sandbox \
    && mkdir -p /work/out && chown sandbox:sandbox /work/out && chmod 700 /work/out

RUN mkdir -p /app

COPY test.sh test_outputs.py /tests/
COPY holdout/ /tests/holdout/

RUN chmod +x /tests/test.sh

WORKDIR /tests

CMD ["/tests/test.sh"]
