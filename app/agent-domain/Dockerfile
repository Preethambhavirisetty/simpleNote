# Single stage on purpose: the dependency tree here is dominated by torch, and
# a builder stage would need it on disk twice (once in /deps, once copied into
# the final image) plus a temporary blob. On a small host that is the
# difference between building and running out of space.
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME="/app/.cache/huggingface" \
    SENTENCE_TRANSFORMERS_HOME="/app/.cache/sentence-transformers"

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8100

# The embedding model downloads on first boot and is cached in the mounted
# volume, so the first start is slower than later ones.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8100"]
