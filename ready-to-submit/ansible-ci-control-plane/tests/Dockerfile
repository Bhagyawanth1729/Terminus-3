FROM public.ecr.aws/docker/library/python:3.13-slim-bookworm@sha256:01f42367a0a94ad4bc17111776fd66e3500c1d87c15bbd6055b7371d39c124fb

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN python -m pip install --no-cache-dir \
        pytest==8.3.4 \
        pytest-json-ctrf==0.3.5 \
        requests==2.32.3

# Parent directory for the declared artifact. test.sh creates verifier logs at runtime.
RUN mkdir -p /app/var/ci-server /tests

# Separate-verifier mode skips host upload of tests/; bake them into the image.
COPY test.sh test_outputs.py /tests/
RUN chmod 0755 /tests/test.sh \
    && test -f /tests/test.sh \
    && test -f /tests/test_outputs.py

WORKDIR /app
