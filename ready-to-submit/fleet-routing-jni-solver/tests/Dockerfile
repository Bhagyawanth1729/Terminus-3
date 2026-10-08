# Terminal-Bench 3.0 Verifier Container
FROM ubuntu:22.04@sha256:67215e9113e9a44e27d6956fe9cb642f4b3ba117c01476b7e65fc12c47864f13

ENV DEBIAN_FRONTEND=noninteractive
ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 \
    PATH=/usr/lib/jvm/java-17-openjdk-amd64/bin:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends \
    openjdk-17-jdk \
    python3 \
    python3-pip \
    procps \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir pytest==7.4.4

RUN mkdir -p /app

WORKDIR /tests
COPY . /tests

ENTRYPOINT ["/tests/test.sh"]
