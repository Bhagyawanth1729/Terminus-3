FROM public.ecr.aws/docker/library/gcc:13-bookworm@sha256:930f2ebe239275fa67226654cb79273ea34eee672ae61c8a39f689c37fb7ac5c

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        cargo \
        golang-go \
        python3 \
        python3-venv \
        rustc \
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
