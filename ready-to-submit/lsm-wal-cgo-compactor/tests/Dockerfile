FROM golang:1.22-bookworm@sha256:45657a8a61427c3d9b4b01e23f956c32d96c464bf210c495e8081fef1394c8e7

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        libc6-dev \
        make \
        python3 \
        python3-pip \
        python3-venv \
        rustc \
        cargo \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /venv \
    && /venv/bin/pip install --no-cache-dir pytest==8.1.1 pytest-json-ctrf==0.1.7

RUN useradd --system --uid 12000 --user-group --no-create-home --shell /usr/sbin/nologin sandbox \
    && mkdir -p /work/out && chown sandbox:sandbox /work/out && chmod 700 /work/out

RUN mkdir -p /app /tests

COPY test.sh test_outputs.py /tests/
COPY holdout/ /tests/holdout/
