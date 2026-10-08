FROM public.ecr.aws/docker/library/ubuntu:22.04@sha256:67210e803715e729a4303be1897d264563af4b2c15e3c880ec187a552fb4dbda

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        asciinema \
        ca-certificates \
        tmux \
        openjdk-17-jdk \
        python3 \
        python3-pip \
        rustc \
        cargo \
        gcc \
        g++ \
        make \
    && rm -rf /var/lib/apt/lists/*

COPY app/ /app/

RUN chmod +x /app/build_and_run.sh \
    && cd /app/rust_aligner && cargo build --release \
    && cd /app/java_gateway && mkdir -p bin && javac -d bin src/main/java/com/terminus/genomics/*.java

ENV PYTHONPATH=/app
