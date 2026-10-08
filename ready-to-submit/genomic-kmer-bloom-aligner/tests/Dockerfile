FROM public.ecr.aws/docker/library/ubuntu:22.04@sha256:67210e803715e729a4303be1897d264563af4b2c15e3c880ec187a552fb4dbda

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 \
        python3-venv \
        openjdk-17-jdk \
        rustc \
        cargo \
        gcc \
        g++ \
        make \
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
