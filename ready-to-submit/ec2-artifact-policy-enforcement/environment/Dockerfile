FROM public.ecr.aws/docker/library/golang:1.24-bookworm@sha256:1a6d4452c65dea36aac2e2d606b01b4a029ec90cc1ae53890540ce6173ea77ac

LABEL org.opencontainers.image.title="EC2 artifact policy enforcement lab"
LABEL org.opencontainers.image.version="1.0"

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates tmux asciinema \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app/enforcer
COPY enforcer/ /app/enforcer/
RUN go build -o /usr/local/bin/artifactguard ./cmd/artifactguard \
 && mkdir -p /app/enforcer/state /app/enforcer/out

ENV ENFORCER_ROOT="/app/enforcer"
