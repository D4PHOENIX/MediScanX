# Stage 1 – builder: install Python dependencies
FROM python:3.11-slim AS builder

# Install uv cleanly from the official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Use the locked requirements via uv
COPY pyproject.toml uv.lock ./

# Install dependencies using Docker BuildKit cache mount so packages are
# cached on the daemon disk between builds and not re-downloaded on every run.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-install-project --no-dev

# Stage 2 – production runtime
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src"

# Install curl (HEALTHCHECK)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create a dedicated non-root user (mediscan) before copying any application code
RUN groupadd -r mediscan && useradd -r -g mediscan mediscan

WORKDIR /app

# Copy the environment from the builder stage
COPY --from=builder --chown=mediscan:mediscan /app/.venv /app/.venv

# Copy application source tree so it is importable via PYTHONPATH=/app/src
COPY --chown=mediscan:mediscan ./src /app/src

USER mediscan

# The Skin microservice listens on port 8003
EXPOSE 8003

# Periodic liveness probe
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8003/healthz || exit 1

# Start the ASGI server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003"]
