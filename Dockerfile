# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

# Install curl for ECS container health checks
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first (layer-cached unless requirements change)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Build metadata — set at build time, readable at runtime
ARG BUILD_COMMIT=unknown
ENV BUILD_COMMIT=$BUILD_COMMIT

# Create uploads directory
RUN mkdir -p /app/uploads

EXPOSE 8000

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
