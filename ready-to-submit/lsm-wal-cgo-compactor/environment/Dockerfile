FROM golang:1.22-bookworm@sha256:45657a8a61427c3d9b4b01e23f956c32d96c464bf210c495e8081fef1394c8e7

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        asciinema \
        ca-certificates \
        gcc \
        g++ \
        libc6-dev \
        make \
        python3 \
        python3-pip \
        rustc \
        cargo \
        tmux \
    && rm -rf /var/lib/apt/lists/*

COPY app/ /app/

ENV PYTHONPATH=/app
ENV PATH="/app/bin:${PATH}"
