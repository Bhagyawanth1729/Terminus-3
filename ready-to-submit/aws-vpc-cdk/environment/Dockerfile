FROM public.ecr.aws/docker/library/node:22-bookworm-slim@sha256:f3a68cf41a855d227d1b0ab832bed9749469ef38cf4f58182fb8c893bc462383

LABEL org.opencontainers.image.title="aws-vpc-cdk" \
      org.opencontainers.image.version="1.0.0" \
      org.opencontainers.image.source="https://github.com/anonymous/terminus-edition-3" \
      org.opencontainers.image.licenses="Apache-2.0"

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    NODE_ENV=development \
    PATH=/app/cdk-vpc/node_modules/.bin:/usr/local/bin:/usr/bin:/bin

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        asciinema \
        bash \
        ca-certificates \
        python3 \
        tmux \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/cdk-vpc
COPY cdk-vpc/package.json cdk-vpc/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY cdk-vpc/ /app/cdk-vpc/
COPY config/ /app/config/
COPY docs/ /app/docs/
RUN chmod 0755 /app/cdk-vpc/bin/synth.js \
    && mkdir -p /app/cdk.out

CMD ["sleep", "infinity"]
