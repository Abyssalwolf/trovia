FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    TROVIA_DATA_DIR=/app/data

RUN pip install --no-cache-dir uv

WORKDIR /app

# Dependencies first so code edits don't invalidate this layer.
COPY pyproject.toml uv.lock* README.md ./
RUN uv sync --no-dev --no-install-project

COPY trovia ./trovia
RUN uv sync --no-dev

EXPOSE 8000
# 0.0.0.0 is the container's own interface; compose publishes the port on 127.0.0.1 only.
CMD ["/app/.venv/bin/trovia", "serve", "--host", "0.0.0.0", "--port", "8000"]
