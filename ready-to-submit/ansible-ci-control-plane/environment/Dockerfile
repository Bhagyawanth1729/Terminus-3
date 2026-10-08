# Go is the primary language of the control plane and the deployment compiles it
# in place, so the canonical Go base image is the runtime here. Ansible and
# supervisord are layered on top of it from Debian bookworm packages.
FROM public.ecr.aws/docker/library/golang:1.24-bookworm@sha256:1a6d4452c65dea36aac2e2d606b01b4a029ec90cc1ae53890540ce6173ea77ac

LABEL org.opencontainers.image.title="ci-control-plane" \
      org.opencontainers.image.version="3.1.0" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.created="2026-01-01T00:00:00Z"

ENV DEBIAN_FRONTEND=noninteractive \
    GOCACHE=/tmp/ci-server-gocache \
    GOTOOLCHAIN=local \
    LANG=C.UTF-8

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        asciinema \
        ca-certificates \
        curl \
        jq \
        procps \
        python3 \
        python3-pip \
        supervisor \
        tmux \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir --break-system-packages ansible-core==2.17.6

# Debian's /etc/profile rewrites PATH for root, so a login shell would otherwise
# lose the Go toolchain that the deployment shells out to.
RUN ln -s /usr/local/go/bin/go /usr/local/bin/go \
    && ln -s /usr/local/go/bin/gofmt /usr/local/bin/gofmt

WORKDIR /app

# Agent image is environment/ only. solution/ and tests/ are never copied here;
# the verifier runs in a separate image (task.toml environment_mode=separate).
COPY deploy/supervisord.conf /etc/supervisor/supervisord.conf
COPY bin/ci-server-apply /app/bin/ci-server-apply
COPY docs/ /app/environment/docs/
COPY ansible/ /app/environment/ansible/
COPY ci-server/ /app/environment/ci-server/

# Normalise the permissions the build context carries so Ansible does not treat
# its own configuration directory as world writable.
RUN chmod 0755 /app/bin/ci-server-apply \
    && chmod -R go-w /app/environment /app/bin \
    && mkdir -p /var/log/supervisor /app/var

# Warm the module build cache so the first deployment run is not dominated by
# compiling the standard library.
RUN cd /app/environment/ci-server && go build ./...
