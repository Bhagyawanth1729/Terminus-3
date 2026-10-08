# Terminal-Bench 3.0 Task Environment
FROM ubuntu:22.04@sha256:67215e9113e9a44e27d6956fe9cb642f4b3ba117c01476b7e65fc12c47864f13

ENV DEBIAN_FRONTEND=noninteractive
ENV RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo \
    PATH=/usr/local/cargo/bin:/usr/local/go/bin:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    ca-certificates \
    python3 \
    python3-pip \
    python3-dev \
    golang-go \
    procps \
    pkg-config \
    tmux \
    asciinema \
    && rm -rf /var/lib/apt/lists/*

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain 1.75.0

RUN pip3 install --no-cache-dir numpy==1.26.3 pytest==7.4.4

WORKDIR /app
COPY app /app

RUN chmod +x /app/build_all.sh && /app/build_all.sh

CMD ["/bin/bash"]
