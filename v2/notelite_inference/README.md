# AI-inference-service

HTTP API for LLM inference and embeddings (llama.cpp, C++). Supports **summarization** (chat/completion) and **embedding** modes; optional API key and multi-turn conversation history for `/infer`. See **[DOCUMENTATION.md](DOCUMENTATION.md)** for architecture, features, improvements, and scalability.

Quick setup (macOS + local llama.cpp build):
```bash
cd /Users/preethambhavirisetty/simpleNote/v2/notelite_inference
chmod +x ./setup_llama.sh
./setup_llama.sh
```
This script:
- installs `cmake` (via Homebrew) if missing
- clones `llama.cpp`
- builds `./build/inference_api`
- creates `.env.llama` with `MODEL_PURPOSE_SUMMARIZATION` and `MODEL_PURPOSE_CHAT`

## Features

- **Dynamic model loading**: Run in **embedding** mode (e.g. phi) or **summarization** mode (mistral / llama3). Tuned for A100 80GB: 32K context for summarization, 4K for embedding, 8K batch for long prompts.
- **Longer conversation history**: `POST /infer` accepts JSON with `prompt` and optional `history` array of `{ "role": "user"|"assistant", "content": "..." }` for multi-turn prompts.
- **Docker**: Two instances—one for embedding, one for summarization—via `docker-compose`.
- **API key** (optional): If you set `--api-key=KEY`, the service that calls `/infer` or `/embed` must send the same secret (shared secret) via `Authorization: Bearer KEY` or `X-Api-Key: KEY`. If you do not set `--api-key`, no auth is required.

## Build and run

### Setup
```bash
git clone https://github.com/ggml-org/llama.cpp.git
```

### CPU only

```bash
cd /home/labadmin/splunk_ai_team_project/AI-inference-service
mkdir -p build
cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)

# Terminal 1
export LLAMA_MODEL_PATH=../models/mistral_7b_instruct_v0_2_Q5_K_M.gguf
./inference_api --port=8081

# Terminal 2
export LLAMA_MODEL_PATH=../models/Meta-Llama-3.1-8B-Instruct-Q5_K_M.gguf
./inference_api --port=8082
```

### With CUDA (NVIDIA GPU)

Requires NVIDIA drivers and [CUDA Toolkit](https://developer.nvidia.com/cuda-downloads) installed. Then:

```bash
cd /home/labadmin/splunk_ai_team_project/AI-inference-service
mkdir -p build
cd build
cmake .. -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=ON
make -j$(nproc)
```

The binary is the same; at runtime the model will use the GPU (you should see layers assigned to a CUDA device in the logs instead of CPU). For a specific GPU architecture (e.g. A100), you can set:

```bash
cmake .. -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=80
```

(80 = A100; 90 = H100; omit for default multi-arch.)

### Run

```bash
./inference_api --mode=summarization
# or
./inference_api --mode=embedding
# with optional API key:
./inference_api --mode=summarization --api-key=your-secret
```

- **Embedding**: `--mode=embedding` → loads embedding model, exposes `POST /embed` (body = text, response = `{"embedding":[...]}`).
- **Summarization**: `--mode=summarization` (default) → loads LLM, exposes `POST /infer` (body = prompt text or JSON with `prompt` + `history`). Optional query param **`?purpose=summary`** or **`?purpose=query_parsing`** selects which model to use: `summary` → Mistral 7B (or `MODEL_PURPOSE_SUMMARY`), `query_parsing` → Phi 3.5 mini (or `MODEL_PURPOSE_QUERY_PARSING`). Omitted `purpose` uses `LLAMA_MODEL_PATH` or default.

Set `LLAMA_MODEL_PATH` for a single-model fallback. Set `MODEL_PURPOSE_SUMMARIZATION` and `MODEL_PURPOSE_CHAT` to pin different files for each purpose. Set `SERVICE_MODE=embedding|summarization` to override `--mode`.

## Docker

```bash
# Build (llama.cpp must exist in the project)
docker-compose build

# Run both services (mount dir with embedding.gguf and summarization.gguf)
API_KEY=your-secret docker-compose up -d
```

**Checklist to get high performance inference:**
Model Loading (llama_model)
Context Management (llama_context)
Batching System (llama_batch)
Thread Management, n_threads
GPU Offloading (n_gpu_layers)
KV Cache Management(Use llama_kv_cache_clear and llama_kv_cache_seq_rm)
Memory Mapping (mmap): Ensure use_mmap = true
Unified Memory
Tokenization: llama_tokenize
Sampling Pipeline: llama_sampler: Temperature, Top-K / Top-P, Min-P, Repeat Penalty
Logit Processors
Streaming Output: Use a callback or a queue system so the user sees tokens as they are generated, rather than waiting for the whole paragraph.
Grammar Constraints (gbnf): Integrate GBNF grammars to force the model to output valid JSON or specific formats—crucial for RAG agents.
Context Shifting: If a conversation exceeds the 8k or 32k limit, implement "Smart Truncation" or "Rolling Window" so the model doesn't "forget" the beginning of the prompt.
Graceful Shutdown: Properly call llama_free, llama_free_model, and llama_backend_free to prevent memory leaks in your C++ process.
use LongRoPE or Flash Attention: This ensures that as your "Context" grows, the response time doesn't skyrocket past that 8s mark.

-> measure success by Tokens Per Second (TPS) rather than total time.

**Endpoints with requests & response structures**

> All endpoints that mutate state or invoke inference require the `Authorization: Bearer <key>` or `X-Api-Key: <key>` header when the server is started with `--api-key`. Auth-free by default.

---

### `GET /ping`
Liveness probe. No auth required.

```
Response 200  text/plain
pong
```

---

### `GET /health`
Readiness probe. No auth required.

```json
// Response 200
{ "status": "ok", "service": "inference-api" }
```

---

### `GET /v1/models`
Lists models known to this server. Used by OpenAI-compatible clients (e.g. LlamaIndex `OpenAILike`) on startup.

```json
// Response 200
{
  "object": "list",
  "data": [
    { "id": "llama-3.1-8b",  "object": "model", "created": 0, "owned_by": "notelite" },
    { "id": "mistral-7b",    "object": "model", "created": 0, "owned_by": "notelite" },
    { "id": "gpt-3.5-turbo", "object": "model", "created": 0, "owned_by": "notelite" }
  ]
}
```

---

### `POST /v1/chat/completions` _(summarization mode only)_

OpenAI-compatible chat completion. The agent's LlamaIndex `OpenAILike` client hits this endpoint.

**Query params**

| Param | Values | Default |
|-------|--------|---------|
| `purpose` | `summary` \| `query_parsing` | resolved from `model` field |

Model routing (when `purpose` is not set explicitly):
- `model: "mistral*"` → `query_parsing` → loads Mistral 7B (greedy, temp=0)
- anything else (incl. `"gpt-3.5-turbo"`) → `summary` → loads Llama-3.1-8B (temp=0.4)

**Request**

```json
{
  "model": "gpt-3.5-turbo",
  "messages": [
    { "role": "system",    "content": "You are a helpful assistant." },
    { "role": "user",      "content": "Summarise the following notes:\n\n..." },
    { "role": "assistant", "content": "Here is a summary: ..." },
    { "role": "user",      "content": "What was the main topic?" }
  ],
  "temperature": 0.4,
  "max_tokens": 512,
  "stream": false
}
```

`messages` is the only required field. `temperature` and `max_tokens` override the server-side sampling preset when provided.

**Response 200**

```json
{
  "id": "chatcmpl-68123abc",
  "object": "chat.completion",
  "created": 1700000000,
  "model": "gpt-3.5-turbo",
  "choices": [{
    "index": 0,
    "message": {
      "role": "assistant",
      "content": "The main topic was project planning and budget allocation."
    },
    "finish_reason": "stop"
  }],
  "usage": { "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0 }
}
```

**Error responses**

| Code | Reason |
|------|--------|
| 400  | Missing or malformed `messages` array |
| 401  | Invalid or missing API key |
| 413  | Request body > 128 KB |
| 500  | Model load failure or inference error |
| 501  | `stream: true` requested (not yet supported) |

**Example — curl**

```bash
curl -s http://localhost:8081/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-3.5-turbo",
    "messages": [
      {"role": "user", "content": "What is 2 + 2?"}
    ],
    "temperature": 0.4,
    "max_tokens": 128
  }' | python3 -m json.tool
```

**Example — query_parsing (Mistral, greedy)**

```bash
curl -s "http://localhost:8081/v1/chat/completions?purpose=query_parsing" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "mistral-7b",
    "messages": [
      {
        "role": "system",
        "content": "You are a JSON-only intent parser. Output a single valid JSON object, no extra text."
      },
      {
        "role": "user",
        "content": "Summarise power consumption for site RCDN lab rcdn05-g41 row A over the past 6 months."
      }
    ],
    "temperature": 0.0,
    "max_tokens": 256
  }'
```

---

### `POST /embed` _(embedding mode only)_

Returns the embedding vector for a plain-text body.

**Request**

```
POST /embed
Content-Type: text/plain          (or omit; body is treated as raw text)

The quick brown fox jumps over the lazy dog.
```

**Response 200**

```json
{
  "embedding": [0.0142, -0.0381, 0.0274, "..."]
}
```

**Error responses**

| Code | Reason |
|------|--------|
| 400  | Empty body |
| 401  | Invalid or missing API key |
| 413  | Body > 65 536 bytes |
| 500  | Embedding failed |

**Example — curl**

```bash
curl -s http://localhost:8081/embed \
  -H "Content-Type: text/plain" \
  --data "The quick brown fox jumps over the lazy dog." \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'dims={len(d[\"embedding\"])}')"
```

---


**⚠️ Bug note (fixed):** An earlier test produced garbled output with `<|eot_id|><|start_header_id|>assistant<|end_header_id|>` appearing inline and the model never stopping. Root cause: `llama_tokenize` was called with `parse_special=false`, so the Llama-3 special tokens in the chat template were tokenized as individual characters instead of their single-token IDs. The model never received a proper chat-format prompt and never generated a real EOG token. Fixed by using `parse_special=true` when a chat template is active (i.e. `add_bos=false`) and moving the `llama_vocab_is_eog` check before the output append.

**Test request (use this after rebuilding):**

```bash
curl -s http://localhost:8081/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-3.5-turbo",
    "messages": [
      {
        "role": "system",
        "content": "You are a factual assistant. Answer using only the provided context. If the answer is not in the context, say you do not know."
      },
      {
        "role": "user",
        "content": "Context:\nProject Zenith targets early adopters aged 18-24 interested in tech and AI. The ads budget is $50,000 (approved) and social budget is $12,000 (pending).\n\nQuestion: What is the total approved budget and who is the target audience?"
      }
    ],
    "temperature": 0.4,
    "max_tokens": 256
  }' | python3 -m json.tool
```

**Expected response (clean, no special tokens in content):**

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "created": 1700000000,
  "model": "gpt-3.5-turbo",
  "choices": [{
    "index": 0,
    "message": {
      "role": "assistant",
      "content": "The total approved budget is $50,000 (ads). The target audience is early adopters aged 18–24 with interests in tech and AI."
    },
    "finish_reason": "stop"
  }],
  "usage": { "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0 }
}

Sample Request:
{
  "model": "llama-3.1-8b",
  "messages": [
    { 
      "role": "system", 
      "content": "You are a personal assistant. Answer ONLY using the provided context. Connect information across different blogs to answer accurately." 
    },
    { 
      "role": "user", 
      "content": "CONTEXT:\nBlog 1 (Jan 2024): 'Moving Day' - Just finished unpacking at my new place in Seattle. The rain is constant but the coffee is great.\nBlog 2 (Feb 2024): 'Work Update' - Started a new role at 'Vertex Corp'. My commute is only 10 minutes by foot now.\n\nQUESTION:\nBased on my blogs, what city is 'Vertex Corp' located in, and how do you know?" 
    }
  ],
  "temperature": 0.1
}

Response:
{
    "id": "chatcmpl-69c09727",
    "object": "chat.completion",
    "created": 1774229287,
    "model": "llama-3.1-8b",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "Based on the blogs, I can infer that 'Vertex Corp' is located in Seattle. This is because in Blog 1, you mention that you've just moved to Seattle and are unpacking at your new place, and in Blog 2, you mention that your commute to work is only 10 minutes by foot, implying that your workplace is nearby."
            },
            "finish_reason": "stop"
        }
    ],
    "usage": {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0
    }
}


Agent's retrieve:
Request:
{
    "query": "Based on my blogs, what city is 'Vertex Corp' located in, and how do you know?",
    "k": 5,
    "user_id": "SAMPLEUSER01",
    "role": "user",
    "tenant_id": "TENANT01"
}

Response:
"Based on the blogs, I can infer that 'Vertex Corp' is located in Seattle. I know this because in Blog 1, you mentioned that you just finished unpacking at your new place in Seattle, and in Blog 2, you mentioned that your commute to 'Vertex Corp' is only 10 minutes by foot. Since you're commuting on foot, it's likely that 'Vertex Corp' is close to your new place, and given that you're in Seattle, it's reasonable to conclude that 'Vertex Corp' is also located in Seattle."

"Based on the information provided, I can conclude that 'Vertex Corp' is located in Seattle. I know this because in Blog 1, the author mentions that they have just moved to Seattle and are unpacking at their new place. In Blog 2, the author mentions that their commute to work is only 10 minutes by foot, which suggests that they are still in Seattle."
