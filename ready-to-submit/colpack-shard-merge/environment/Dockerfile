# Agent image. Nothing from tests/ or solution/ may ever be copied in here.
FROM public.ecr.aws/docker/library/rust:1.84-bookworm@sha256:738ae99a3d75623f41e6882566b4ef37e38a9840244a47efd4a0ca22e9628b88

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        asciinema \
        ca-certificates \
        python3 \
        tmux \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY app/colpack-rs/ /app/colpack-rs/
COPY app/pipeline/ /app/pipeline/
COPY app/docs/ /app/docs/
COPY app/config/ /app/config/
COPY app/data/ /app/data/
COPY app/logs/ /app/logs/

RUN cd /app/colpack-rs && cargo build --release

ENV PYTHONPATH=/app/pipeline
