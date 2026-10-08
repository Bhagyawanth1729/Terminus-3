# Terminal-Bench 3.0 Verifier Container
FROM ubuntu:22.04@sha256:67215e9113e9a44e27d6956fe9cb642f4b3ba117c01476b7e65fc12c47864f13

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    procps \
    curl \
    libnetcdf-dev \
    libhdf5-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /venv \
    && /venv/bin/pip install --no-cache-dir \
        pytest==7.4.4 \
        pytest-json-ctrf==0.1.1 \
        numpy==1.26.4 \
        scipy==1.13.0 \
        netCDF4==1.6.5

RUN useradd --system --uid 12000 --user-group --no-create-home --shell /usr/sbin/nologin sandbox \
    && mkdir -p /work/out && chown sandbox:sandbox /work/out && chmod 700 /work/out

RUN mkdir -p /app

COPY test.sh test_outputs.py /tests/
COPY holdout/ /tests/holdout/

WORKDIR /tests
ENTRYPOINT ["/tests/test.sh"]
