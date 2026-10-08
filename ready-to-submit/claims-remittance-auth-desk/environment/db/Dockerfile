FROM docker.io/library/postgres:16-bookworm@sha256:c95fd5346040eba2de3c435e14874af18f5d681fb5848d4f081dbead0878af28

LABEL org.opencontainers.image.title="claims-database" \
      org.opencontainers.image.version="1.0.0" \
      org.opencontainers.image.licenses="PostgreSQL"

COPY schema.sql /docker-entrypoint-initdb.d/010-claims.sql
