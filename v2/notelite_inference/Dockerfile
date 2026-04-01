# ── Stage 1: build ─────────────────────────────────────────────────────────────
FROM ubuntu:22.04 AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

RUN if [ ! -f llama.cpp/CMakeLists.txt ]; then \
    git clone --depth 1 https://github.com/ggml-org/llama.cpp.git; fi

RUN mkdir -p build && cd build \
    && cmake .. -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF \
    && make -j"$(nproc)"

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM ubuntu:22.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    libstdc++6 \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -r -s /usr/sbin/nologin inference

WORKDIR /app
COPY --from=builder /app/build/inference_api /app/inference_api
RUN chmod +x /app/inference_api

USER inference

ENV SERVICE_MODE=summarization \
    LLAMA_MODEL_PATH=

EXPOSE 8081

STOPSIGNAL SIGTERM

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -sf http://localhost:8081/health || exit 1

CMD ["/bin/sh", "-c", "exec /app/inference_api --mode=$SERVICE_MODE ${API_KEY:+--api-key=$API_KEY}"]
