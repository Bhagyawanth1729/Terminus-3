# Terminal-Bench 3.0 Task Environment
FROM ubuntu:22.04@sha256:67215e9113e9a44e27d6956fe9cb642f4b3ba117c01476b7e65fc12c47864f13

ENV DEBIAN_FRONTEND=noninteractive
ENV RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo \
    PATH=/usr/local/cargo/bin:$PATH \
    PYTHONPATH=/app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    ca-certificates \
    tmux \
    asciinema \
    procps \
    pkg-config \
    python3 \
    python3-pip \
    python3-dev \
    libnetcdf-dev \
    libhdf5-dev \
    && rm -rf /var/lib/apt/lists/*

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain 1.75.0

RUN pip3 install --no-cache-dir \
    numpy==1.26.4 \
    scipy==1.13.0 \
    netCDF4==1.6.5 \
    xarray==2024.3.0 \
    pytest==7.4.4

WORKDIR /app
COPY app /app

RUN chmod +x /app/build.sh && /app/build.sh

CMD ["/bin/bash"]
