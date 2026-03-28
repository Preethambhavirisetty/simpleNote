# Build: run from repo root with llama.cpp present (clone into project per README)
FROM ubuntu:22.04 AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

# If llama.cpp not present, clone it
RUN if [ ! -f llama.cpp/CMakeLists.txt ]; then \
    git clone --depth 1 https://github.com/ggml-org/llama.cpp.git; fi

RUN mkdir -p build && cd build \
    && cmake .. -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF \
    && make -j2

# Runtime — static build needs no shared libs, just the binary
FROM ubuntu:22.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    libstdc++6 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /app/build/inference_api /app/inference_api

ENV SERVICE_MODE=summarization
ENV LLAMA_MODEL_PATH=
EXPOSE 8081

CMD ["/bin/sh", "-c", "exec /app/inference_api --mode=$SERVICE_MODE ${API_KEY:+--api-key=$API_KEY}"]
