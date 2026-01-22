# Boswell AI Research Interviewer
# Python 3.11 slim base image

FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Set working directory
WORKDIR /app

# Install system dependencies (for potential audio/PDF processing)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files first (for better layer caching)
COPY pyproject.toml ./

# Install Python dependencies
RUN pip install --upgrade pip && \
    pip install .

# Copy source code
COPY src/ ./src/

# Re-install to link the package properly
RUN pip install -e .

# Create outputs directory
RUN mkdir -p /app/outputs

# Set the entry point to the Boswell CLI
ENTRYPOINT ["boswell"]

# Default command (show help)
CMD ["--help"]
