# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

# Install curl for the in-container HEALTHCHECK below and for ECS's check.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user to run the app under. UID 1000 is the conventional
# first non-system user; matching it makes mounted-volume permissions
# predictable on Linux hosts.
RUN useradd --create-home --uid 1000 appuser

# Install dependencies first (layer-cached unless requirements change).
# Done as root so packages install system-wide under /usr/local.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy source with appuser ownership in a single layer.
COPY --chown=appuser:appuser . .

# Build metadata — set at build time, readable at runtime.
ARG BUILD_COMMIT=unknown
ENV BUILD_COMMIT=$BUILD_COMMIT

# Create the uploads directory owned by appuser so the running app can
# write to it. Note: when a Docker volume is mounted over this path, the
# volume's existing ownership wins. Local-dev volumes created before this
# change will be root-owned — recreate them once with
#     docker compose down -v && docker compose up -d --build
# In ECS prod, file storage is S3 so this path is unused.
RUN mkdir -p /app/uploads && chown appuser:appuser /app/uploads

USER appuser

# Docker's own healthcheck. Independent of ECS's (which is defined in the
# task definition); mostly valuable for `docker compose up` so the
# container auto-marks unhealthy if the app dies. start-period covers
# Alembic upgrade + seed loader on first boot.
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -sf http://localhost:8000/health || exit 1

EXPOSE 8000

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
