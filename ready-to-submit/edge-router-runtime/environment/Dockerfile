FROM public.ecr.aws/docker/library/golang:1.24-bookworm@sha256:1a6d4452c65dea36aac2e2d606b01b4a029ec90cc1ae53890540ce6173ea77ac

LABEL org.opencontainers.image.source="https://github.com/Manoj-Kumar-Selvaraj/Terminus-Edition-3" \
      org.opencontainers.image.version="3" \
      org.opencontainers.image.licenses="MIT"

RUN apt-get update \
    && apt-get install -y --no-install-recommends tmux asciinema ca-certificates curl jq xz-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/edge-router
COPY go.mod ./
COPY cmd ./cmd
COPY internal ./internal
COPY config ./config
COPY docs ./docs
RUN go build -o /usr/local/bin/edge-router-runtime ./cmd/edge-router-runtime
RUN mkdir -p /app/state

EXPOSE 8080 9901
CMD ["/usr/local/bin/edge-router-runtime","serve","--config","/app/edge-router/config/production.json","--state-dir","/app/state","--listen",":8080","--admin-listen",":9901"]
