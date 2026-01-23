# Boswell AI Research Interviewer
# Multi-stage Dockerfile for web server and voice worker
#
# Usage:
#   Web service:    docker run -e ... boswell ./scripts/start_web.sh
#   Voice worker:   docker run -e ... boswell ./scripts/start_worker.sh

# =============================================================================
# Stage 1: Builder - Install dependencies
# =============================================================================
FROM python:3.11-slim as builder

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy package files needed for build
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Install all dependencies (base + server + voice)
RUN pip install --upgrade pip && \
    pip wheel --no-deps --wheel-dir /app/wheels . && \
    pip wheel --wheel-dir /app/wheels .[server,voice]

# =============================================================================
# Stage 2: Runtime - Final image
# =============================================================================
FROM python:3.11-slim as runtime

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

# Install runtime dependencies
# - libpq for PostgreSQL (asyncpg)
# - libsndfile for audio processing (pipecat)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Copy wheels from builder and install
COPY --from=builder /app/wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

# Copy source code
COPY src/ ./src/
COPY alembic.ini ./
COPY scripts/ ./scripts/

# Make scripts executable
RUN chmod +x ./scripts/*.sh

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash appuser && \
    chown -R appuser:appuser /app
USER appuser

# Expose port for web service
EXPOSE 8000

# Default command - uses SERVICE_TYPE env var to select web or worker
# Set SERVICE_TYPE=worker for voice worker, otherwise runs web server
CMD ["./scripts/entrypoint.sh"]
