FROM ubuntu:22.04@sha256:67215e9113e9a44e27d6956fe9cb642f4b3ba117c01476b7e65fc12c47864f13

ENV DEBIAN_FRONTEND=noninteractive
ENV RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo \
    PATH=/usr/local/cargo/bin:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    ca-certificates \
    python3 \
    python3-venv \
    python3-dev \
    pkg-config \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain 1.75.0

RUN python3 -m venv /venv \
    && /venv/bin/pip install --no-cache-dir pyarrow==14.0.2 numpy==1.26.3 pytest==7.4.4 pytest-json-ctrf==0.5.2

RUN useradd --system --uid 12000 --user-group --no-create-home --shell /usr/sbin/nologin sandbox \
    && mkdir -p /work/out && chown sandbox:sandbox /work/out && chmod 700 /work/out

COPY test.sh test_outputs.py /tests/
COPY holdout/ /tests/holdout/
RUN chmod -R a+rX /tests/holdout

RUN mkdir -p /app

ENTRYPOINT ["/tests/test.sh"]
