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
    python3-pip \
    python3-dev \
    pkg-config \
    libssl-dev \
    tmux \
    asciinema \
    && rm -rf /var/lib/apt/lists/*

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain 1.75.0

RUN pip3 install --no-cache-dir pyarrow==14.0.2 numpy==1.26.3 pytest==7.4.4

WORKDIR /app
COPY app /app

RUN python3 /app/data/generate_data.py \
    && chmod +x /app/build.sh \
    && /app/build.sh

CMD ["/bin/bash"]
