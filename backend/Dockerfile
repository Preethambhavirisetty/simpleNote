# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build tools needed by some C-extension packages (psycopg binary wheel
# bundles libpq, so no extra system libs are required here).
RUN pip install --no-cache-dir --upgrade pip

COPY requirements.txt .

# Install packages into /deps so we can copy only that layer to the final image.
RUN pip install --no-cache-dir --prefix=/deps -r requirements.txt


# ── Stage 2: minimal runtime image ────────────────────────────────────────────
FROM python:3.12-slim

# Security: run as a non-root user.
RUN addgroup --system app \
 && adduser  --system --ingroup app --no-create-home app

WORKDIR /app

# Bring in packages installed by the builder stage.
COPY --from=builder /deps /usr/local

# Copy only the application source; tests, local config, and the venv stay out.
COPY --chown=app:app app/ ./app/

# Database migrations (applied before the app starts, via the entrypoint below).
COPY --chown=app:app alembic/ ./alembic/
COPY --chown=app:app alembic.ini ./alembic.ini
COPY --chown=app:app docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

USER app

# Prevent Python from writing .pyc files and buffer stdout/stderr so logs
# appear immediately in container logs.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# Lightweight health-check using Python's built-in urllib; avoids installing curl.
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c \
        "import urllib.request, sys; \
         r = urllib.request.urlopen('http://localhost:8000/api/health', timeout=5); \
         sys.exit(0 if r.status == 200 else 1)" \
        || exit 1

# Runtime environment variables must be supplied by the orchestrator / Compose.
# Required: POSTGRES_DB_URL, SECRET_KEY
# Optional: HASH_ALGORITHM (default: HS256)
# The entrypoint runs `alembic upgrade head` (retrying until Postgres is ready),
# then execs the CMD below.
ENTRYPOINT ["/app/docker-entrypoint.sh"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
