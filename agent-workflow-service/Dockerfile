FROM python:3.12-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/deps -r requirements.txt

FROM python:3.12-slim

RUN addgroup --system app && adduser --system --ingroup app --no-create-home app

WORKDIR /app

COPY --from=builder /deps /usr/local
COPY --chown=app:app app ./app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    TIKTOKEN_CACHE_DIR=/app/.cache/tiktoken \
    AGENT_WORKFLOW_HOST=0.0.0.0 \
    AGENT_WORKFLOW_PORT=5453

RUN mkdir -p /app/.cache/tiktoken && chown -R app:app /app/.cache

USER app

RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"

EXPOSE 5453

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; r=urllib.request.urlopen('http://127.0.0.1:5453/health', timeout=5); sys.exit(0 if r.status==200 else 1)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5453"]
