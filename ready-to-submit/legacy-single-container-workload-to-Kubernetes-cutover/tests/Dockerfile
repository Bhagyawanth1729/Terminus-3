FROM public.ecr.aws/docker/library/python:3.13-slim-bookworm@sha256:01f42367a0a94ad4bc17111776fd66e3500c1d87c15bbd6055b7371d39c124fb

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir \
        pytest==8.3.5 \
        pytest-json-ctrf==0.5.3 \
        pyyaml==6.0.2

RUN mkdir -p /app/k8s /app/inventory /logs/verifier /tests

# Sealed inventory copy so the verifier does not depend on agent edits.
COPY test.sh test_outputs.py /tests/
COPY fixtures/ /tests/fixtures/
RUN chmod 0755 /tests/test.sh
RUN rm -rf /tests/__pycache__

WORKDIR /app
