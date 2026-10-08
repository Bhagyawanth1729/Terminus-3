FROM public.ecr.aws/docker/library/gcc:13-bookworm@sha256:930f2ebe239275fa67226654cb79273ea34eee672ae61c8a39f689c37fb7ac5c

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        asciinema \
        ca-certificates \
        cargo \
        golang-go \
        python3 \
        rustc \
        tmux \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY app/ /app/

RUN cd /app/librust_verifier && cargo build --release

RUN cd /app/gateway && CGO_ENABLED=1 go build -o gateway .
