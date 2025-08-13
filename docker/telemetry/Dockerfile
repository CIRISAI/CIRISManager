# TimescaleDB with telemetry schema pre-configured
FROM timescale/timescaledb:latest-pg14

# Install additional extensions
RUN apt-get update && \
    apt-get install -y \
    postgresql-14-cron \
    postgresql-14-pg-stat-kcache \
    && rm -rf /var/lib/apt/lists/*

# Copy initialization scripts
COPY init-scripts/ /docker-entrypoint-initdb.d/

# Environment variables
ENV POSTGRES_DB=telemetry
ENV POSTGRES_USER=ciris
ENV POSTGRES_INITDB_ARGS="--encoding=UTF8 --locale=en_US.UTF-8"

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=30s --retries=3 \
    CMD pg_isready -U ciris -d telemetry || exit 1

EXPOSE 5432