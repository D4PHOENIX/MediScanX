# Stage 1: Builder
FROM python:3.10-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Cache dependencies
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

# Copy project files and install the project itself
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Stage 2: Runtime
FROM python:3.10-slim AS runtime

# Install curl for HEALTHCHECK
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Create a dedicated non-root user
RUN groupadd -r mediscan && useradd -r -m -g mediscan mediscan

WORKDIR /app

# Copy application and virtual environment from builder
COPY --from=builder --chown=mediscan:mediscan /app /app

# Ensure virtual environment binaries are on the PATH
ENV PATH="/app/.venv/bin:$PATH"
# Ensure the application package is importable
ENV PYTHONPATH=/app/src

# Drop root privileges for security
USER mediscan

# The agent microservice listens on port 8005
EXPOSE 8005

# Periodic liveness probe
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8005/healthz || exit 1

# Start the ASGI server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8005"]
