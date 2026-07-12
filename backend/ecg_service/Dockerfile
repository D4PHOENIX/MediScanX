# Stage 1 – builder: install Python dependencies
FROM python:3.11-slim AS builder

# Install uv for extremely fast Python dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Copy lockfile and pyproject.toml to install dependencies
COPY pyproject.toml uv.lock ./

# Install dependencies into the virtual environment using uv
ENV UV_NO_CACHE=1
RUN uv sync --no-install-project --no-cache


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

# Create a dedicated non‑root user (mediscan) before copying any application code
RUN groupadd -r mediscan && useradd -r -g mediscan mediscan

# Copy the virtual environment from the builder stage
COPY --from=builder --chown=mediscan:mediscan /app/.venv /app/.venv

# Set the application working directory and copy the service source code
WORKDIR /app
# Copy the application source tree so it is importable via PYTHONPATH=/app/src
COPY --chown=mediscan:mediscan ./src /app/src

# Drop root privileges for security
USER mediscan

# The ECG microservice listens on port 8002
EXPOSE 8002

# Periodic liveness probe – curl hits /healthz which returns 200 only when
# the ONNX session is loaded and the engine is fully initialised.
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8002/healthz || exit 1

# Start the ASGI server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
