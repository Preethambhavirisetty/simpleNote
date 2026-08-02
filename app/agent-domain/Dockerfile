# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

RUN pip install --no-cache-dir --upgrade pip

COPY requirements.txt .

RUN pip install --no-cache-dir --prefix=/deps -r requirements.txt


# ── Stage 2: runtime image ────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /deps /usr/local

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME="/app/.cache/huggingface" \
    SENTENCE_TRANSFORMERS_HOME="/app/.cache/sentence-transformers"

COPY . .

EXPOSE 8100

# The embedding model is downloaded on first boot and cached in the mounted
# volume, so the first start is slower than later ones.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8100"]
