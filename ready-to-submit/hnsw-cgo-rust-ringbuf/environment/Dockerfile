FROM ubuntu:22.04@sha256:67210e80568e6a205a2e5d95d10d1fcfdca298f24446c59b20b22a0a2df33eb8

WORKDIR /app

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        asciinema \
        build-essential \
        ca-certificates \
        curl \
        gcc \
        g++ \
        golang-go \
        make \
        pkg-config \
        python3 \
        python3-dev \
        python3-pip \
        rustc \
        cargo \
        tmux \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir \
    numpy==1.26.4 \
    scipy==1.12.0

COPY app/ /app/

RUN chmod +x /app/build_and_run.sh \
    && python3 /app/generate_data.py \
    && /app/build_and_run.sh || true

ENV PYTHONPATH=/app

CMD ["/bin/bash"]
