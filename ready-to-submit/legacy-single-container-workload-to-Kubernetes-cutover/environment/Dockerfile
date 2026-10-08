# Canonical Python base; agent needs an editor-friendly shell plus
# YAML tooling. No cluster runtime (verifier is static).
FROM public.ecr.aws/docker/library/python:3.13-slim-bookworm@sha256:01f42367a0a94ad4bc17111776fd66e3500c1d87c15bbd6055b7371d39c124fb

ENV DEBIAN_FRONTEND=noninteractive                 PIP_DISABLE_PIP_VERSION_CHECK=1                 PYTHONDONTWRITEBYTECODE=1

RUN apt-get update                 && apt-get install -y --no-install-recommends                     asciinema                     ca-certificates                     curl                     jq                     tmux                     vim-tiny                 && rm -rf /var/lib/apt/lists/*                 && pip install --no-cache-dir pyyaml==6.0.2

WORKDIR /app

COPY app/ /app/app/
COPY inventory/ /app/inventory/
COPY evidence/ /app/evidence/
COPY reference/ /app/reference/
COPY k8s/ /app/k8s/

RUN chmod 0755 /app/app/bin/claims-upload                 && find /app/app -type f -exec chmod a-w {} +                 && find /app/inventory /app/evidence /app/reference -type f -exec chmod a-w {} +

CMD ["/bin/bash", "-l"]
