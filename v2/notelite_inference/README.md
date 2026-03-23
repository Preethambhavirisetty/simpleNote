# AI-inference-service

HTTP API for LLM inference and embeddings (llama.cpp, C++). Supports **summarization** (chat/completion) and **embedding** modes; optional API key and multi-turn conversation history for `/infer`. See **[DOCUMENTATION.md](DOCUMENTATION.md)** for architecture, features, improvements, and scalability.

Note: Clone the official llama.cpp repo into the project before building:
```bash
git clone https://github.com/ggml-org/llama.cpp.git
```

## Features

- **Dynamic model loading**: Run in **embedding** mode (e.g. phi) or **summarization** mode (mistral / llama3). Tuned for A100 80GB: 32K context for summarization, 4K for embedding, 8K batch for long prompts.
- **Longer conversation history**: `POST /infer` accepts JSON with `prompt` and optional `history` array of `{ "role": "user"|"assistant", "content": "..." }` for multi-turn prompts.
- **Docker**: Two instances—one for embedding, one for summarization—via `docker-compose`.
- **API key** (optional): If you set `--api-key=KEY`, the service that calls `/infer` or `/embed` must send the same secret (shared secret) via `Authorization: Bearer KEY` or `X-Api-Key: KEY`. If you do not set `--api-key`, no auth is required.

## Build and run

### Setup
git clone https://github.com/ggml-org/llama.cpp.git
cd include && git clone https://github.com/yhirose/cpp-httplib.git
cd include && git clone https://github.com/nlohmann/json.git

### CPU only

```bash
cd /home/labadmin/splunk_ai_team_project/AI-inference-service
mkdir -p build
cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)
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

Set `LLAMA_MODEL_PATH` for the default model. Set `MODEL_PURPOSE_SUMMARY` and `MODEL_PURPOSE_QUERY_PARSING` to override paths per purpose. Set `SERVICE_MODE=embedding|summarization` to override `--mode`.

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



- **Embedding** on port **8081** (model: `LLAMA_MODEL_PATH` / `models/embedding.gguf`).
- **Summarization** on port **8082** (model: `LLAMA_MODEL_PATH` / `models/summarization.gguf`).

Place your GGUF models in `./models/` and name them `embedding.gguf` and `summarization.gguf`, or set `LLAMA_MODEL_PATH` per service in `docker-compose.yml`.


If we give more context related to questions, it can give clear "clarifying questions"

Test 1: to mistral model
Request:
Prompt:
{
    "prompt": "summarize the power consumption from the site RCDN lab rcdn05-g41 and row A for the past 6 months",
    "history": [
        {
            "role": "user",
            "content": "You are a user prompt parser. Schema: site (string or null), lab (string or null), row (string or null), intent_type (string or null), aggregation (string or null), quarter (string or null), parsing_confidence (number from 0.0 to 1.0), clarity_level ('high' or 'medium' or 'low'), clarifying_questions (array of strings). Output only the JSON object. Use null for any field that is not explicitly stated or cannot be inferred. Do not include any explanation, extra text, markdown, or placeholder or descriptive strings."
        },
        {
            "role": "assistant",
            "content": "Of course, I can assist with that. Please send me the prompt you want parsed, and I will reply with only the JSON output, nothing else."
        }
    ]
}

Output:
 {
"site": "RCDN",
"lab": "rcdn05-g41",
"row": "A",
"intent_type": "summarize power consumption",
"aggregation": "6 months",
"quarter": null,
"parsing_confidence": 0.95,
"clarity_level": "high",
"clarifying_questions": []
}

Test 2: to mistral
Request:
Prompt:
{
    "prompt": "whi are y=u",
    "history": [
        {
            "role": "user",
            "content": "You are a user prompt parser. Schema: site (string or null), lab (string or null), row (string or null), intent_type (string or null), aggregation (string or null), quarter (string or null), parsing_confidence (number from 0.0 to 1.0), clarity_level ('high' or 'medium' or 'low'), clarifying_questions (array of strings). Output only the JSON object. Use null for any field that is not explicitly stated or cannot be inferred. Do not include any explanation, extra text, markdown, or placeholder or descriptive strings."
        },
        {
            "role": "assistant",
            "content": "Of course, I can assist with that. Please send me the prompt you want parsed, and I will reply with only the JSON output, nothing else."
        }
    ]
}

Response:
 {
"site": null,
"lab": null,
"row": null,
"intent_type": "unknown",
"aggregation": null,
"quarter": null,
"parsing_confidence": 0.0,
"clarity_level": "low",
"clarifying_questions": ["Can you please clarify what 'whi are y=u' means?"]
}

Test 3:
{
    "prompt": "What sites are available?",
    "history": [
        {
            "role": "user",
            "content": "You are a user prompt parser. Schema: site (string or null), lab (string or null), row (string or null), intent_type (string or null), aggregation (string or null), quarter (string or null), parsing_confidence (number from 0.0 to 1.0), clarity_level ('high' or 'medium' or 'low'), clarifying_questions (array of strings). Output only the JSON object. Use null for any field that is not explicitly stated or cannot be inferred. Do not include any explanation, extra text, markdown, or placeholder or descriptive strings."
        },
        {
            "role": "assistant",
            "content": "Of course, I can assist with that. Please send me the prompt you want parsed, and I will reply with only the JSON output and make sure to include all fields even though it is null, nothing else."
        }
    ]
}

Response:
 {
"site": null,
"lab": null,
"row": null,
"intent_type": "informational",
"aggregation": null,
"quarter": null,
"parsing_confidence": 1.0,
"clarity_level": "medium",
"clarifying_questions": []
}

Regarding your question, I cannot provide an answer based on the provided conversation alone. The conversation only includes the instruction for me to parse and output a JSON object. To answer your question, you would need to provide the specific sites you are inquiring about.

Test 3:
{
    "prompt": "What labs are available in site rtp?",
    "history": [
        {
            "role": "user",
            "content": "You are a user prompt parser. Schema: site (string or null), lab (string or null), row (string or null), intent_type (string or null), aggregation (string or null), quarter (string or null), parsing_confidence (number from 0.0 to 1.0), clarity_level ('high' or 'medium' or 'low'), clarifying_questions (array of strings). Output only the JSON object. Use null for any field that is not explicitly stated or cannot be inferred. Do not include any explanation, extra text, markdown, or placeholder or descriptive strings."
        },
        {
            "role": "assistant",
            "content": "Of course, I can assist with that. Please send me the prompt you want parsed, and I will reply with only the JSON output, nothing else."
        }
    ]
}

Response:
 {
"site": "rtp",
"lab": null,
"row": null,
"intent_type": "informational",
"aggregation": null,
"quarter": null,
"parsing_confidence": 0.85,
"clarity_level": "medium",
"clarifying_questions": ["Which specific labs are you asking about?"]
}