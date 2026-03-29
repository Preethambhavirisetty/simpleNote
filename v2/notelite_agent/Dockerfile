# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

RUN pip install --no-cache-dir --upgrade pip

COPY requirements.txt .

RUN pip install --no-cache-dir --prefix=/deps -r requirements.txt

RUN PYTHONPATH=/deps/lib/python3.12/site-packages \
    python -m spacy download en_core_web_sm --target /deps/lib/python3.12/site-packages


# ── Stage 2: runtime image ────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /deps /usr/local

COPY . .

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME="/app/.cache/huggingface" \
    LLAMA_INDEX_CACHE_DIR="/app/.cache/llama_index" \
    TRANSFORMERS_CACHE="/app/.cache/huggingface"

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
