FROM python:3.11-slim AS base

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    libpq-dev \
    # WeasyPrint dependencies (for PDF generation)
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

# Install esbuild for JSX → JS transpilation
RUN curl -fsSL https://esbuild.github.io/dl/v0.24.2 | sh \
    && mv esbuild /usr/local/bin/

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Set Python path
ENV PYTHONPATH=/app

# Expose port (Railway / Fly provide PORT env var)
EXPOSE 8000

# Fly.io / multi-service builds (Railway uses final stage = api)
FROM base AS worker
CMD ["python", "-m", "celery", "-A", "workers.celery_app", "worker", "--loglevel=info"]

FROM base AS beat
CMD ["python", "-m", "celery", "-A", "workers.celery_app", "beat", "--loglevel=info"]

FROM base AS api
CMD ["/bin/sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
