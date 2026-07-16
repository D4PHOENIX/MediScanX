# Stage 1 – builder: install Python dependencies
FROM python:3.11-slim AS builder

# Install uv cleanly
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Copy lockfile and pyproject.toml to install dependencies
COPY pyproject.toml uv.lock ./

# Install dependencies into the virtual environment using uv
ENV UV_NO_CACHE=1
RUN uv sync --frozen --no-install-project --no-cache

# Stage 2 – production runtime
FROM python:3.11-slim AS runtime

# Install curl for HEALTHCHECK
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Create a dedicated non-root user for security
RUN groupadd -r mediscan && useradd -r -g mediscan mediscan

# Copy the virtual environment from the builder stage
COPY --from=builder --chown=mediscan:mediscan /app/.venv /app/.venv

# Add venv and src to PATH and PYTHONPATH
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src"

# Copy application source tree so it is importable via PYTHONPATH=/app/src
WORKDIR /app
COPY --chown=mediscan:mediscan ./src /app/src

# Drop root privileges
USER mediscan

# The API Gateway listens on port 8000
EXPOSE 8000

# Periodic liveness probe
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health/healthz || exit 1

# Start the API gateway
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
