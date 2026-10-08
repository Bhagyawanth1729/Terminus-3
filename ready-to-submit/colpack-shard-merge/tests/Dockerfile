# Verifier image.
FROM public.ecr.aws/docker/library/python:3.12-bookworm@sha256:8046f973d3da688b788338c186351f84f98557d136c066c9d4f069e565931917

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 \
        python3-venv \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /venv \
    && /venv/bin/pip install --no-cache-dir pytest==9.1.1 pytest-json-ctrf==0.5.2

RUN useradd --system --uid 12000 --user-group --no-create-home --shell /usr/sbin/nologin sandbox \
    && mkdir -p /work/out \
    && chown sandbox:sandbox /work/out \
    && chmod 700 /work/out

COPY test.sh test_outputs.py /tests/
COPY holdout/ /tests/holdout/
RUN chmod -R a+rX /tests/holdout

RUN mkdir -p /app
