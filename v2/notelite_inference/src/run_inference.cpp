#include "run_inference.h"
#include "model_loader.h"
#include "sampling_config.h"
#include "service_config.h"
#include <cstdlib>
#include <iostream>
#include <map>
#include <mutex>
#include <string>
#include <algorithm>
#include <unistd.h>

// ── Log suppression ───────────────────────────────────────────────────────────

static void llama_log_callback_suppress(ggml_log_level, const char*, void*) {}

void suppress_llama_internal_logs() {
    llama_log_set(llama_log_callback_suppress, nullptr);
}

// ── Model paths ───────────────────────────────────────────────────────────────
//   Two models live in notelite_inference/models/:
//     • mistral_7b_instruct_v0_2_Q5_K_M.gguf     → summarization (summaries, query parsing, question gen)
//     • Meta-Llama-3.1-8B-Instruct-Q5_K_M.gguf   → chat (user Q&A)
//
//   Override at runtime with env vars:
//     MODEL_PURPOSE_SUMMARIZATION  → path for summarization model (Mistral)
//     MODEL_PURPOSE_CHAT           → path for chat model (Llama)
//     LLAMA_MODEL_PATH             → single-model fallback (applies to ALL purposes)

static const char* FILENAME_SUMMARIZATION = "mistral_7b_instruct_v0_2_Q5_K_M.gguf";
static const char* FILENAME_CHAT          = "Meta-Llama-3.1-8B-Instruct-Q5_K_M.gguf";

static std::string resolve_model_file(const char* filename) {
    // Container mount path (docker-compose mounts ./models → /models)
    std::string container_path = std::string("/models/") + filename;
    if (access(container_path.c_str(), R_OK) == 0)
        return container_path;

    // Local development (running from notelite_inference/ or its build/ dir)
    std::string local_path = std::string("models/") + filename;
    if (access(local_path.c_str(), R_OK) == 0)
        return local_path;

    std::string parent_path = std::string("../models/") + filename;
    if (access(parent_path.c_str(), R_OK) == 0)
        return parent_path;

    return container_path;
}

static std::string get_model_path_for_purpose(const std::string& purpose) {
    if (purpose == "summarization") {
        const char* env = std::getenv("MODEL_PURPOSE_SUMMARIZATION");
        if (env && env[0]) return env;
    } else {
        const char* env = std::getenv("MODEL_PURPOSE_CHAT");
        if (env && env[0]) return env;
    }

    // LLAMA_MODEL_PATH acts as a single-model override for any purpose
    const char* gen = std::getenv("LLAMA_MODEL_PATH");
    if (gen && gen[0]) return gen;

    const char* filename = (purpose == "summarization")
        ? FILENAME_SUMMARIZATION
        : FILENAME_CHAT;
    return resolve_model_file(filename);
}

static std::string normalize_purpose(const std::string& purpose) {
    // Backward-compat: map legacy keys to the two canonical purpose names
    if (purpose.empty() || purpose == "default" ||
        purpose == "query_parsing" || purpose == "intent" || purpose == "summary")
        return "summarization";
    if (purpose == "chat" || purpose == "reasoning") return "chat";
    return purpose;
}

// ── Lazy-loading model registry ───────────────────────────────────────────────

static std::map<std::string, ModelContext*> g_models;
static std::mutex g_map_mutex;
static std::mutex g_inference_mutex;

static int env_int(const char* name, int fallback) {
    const char* v = std::getenv(name);
    if (v && v[0]) {
        int n = std::atoi(v);
        if (n > 0) return n;
    }
    return fallback;
}

static ModelContext* ensure_model_loaded(const std::string& purpose_key) {
    {
        std::lock_guard<std::mutex> lk(g_map_mutex);
        auto it = g_models.find(purpose_key);
        if (it != g_models.end() && it->second) return it->second;
    }

    std::string path = get_model_path_for_purpose(purpose_key);
    std::cout << "Loading model for purpose='" << purpose_key << "' from " << path << "\n";

    LoadOptions opts;
    opts.embedding    = (get_service_mode() == ServiceMode::Embedding);
    opts.n_ctx        = opts.embedding ? 4096 : env_int("LLAMA_N_CTX", 8192);
    opts.n_gpu_layers = env_int("LLAMA_N_GPU_LAYERS", 999);

    ModelContext* mc = load_model(path, opts);
    if (!mc) {
        std::cerr << "Model loading failed for purpose='" << purpose_key << "'\n";
        return nullptr;
    }

    std::lock_guard<std::mutex> lk(g_map_mutex);
    auto it = g_models.find(purpose_key);
    if (it != g_models.end() && it->second) {
        cleanup_model(mc);
        return it->second;
    }
    g_models[purpose_key] = mc;
    std::cout << "Model loaded (purpose=" << purpose_key
              << ", n_ctx=" << opts.n_ctx
              << ", n_gpu_layers=" << opts.n_gpu_layers << ").\n";
    return mc;
}

// ── Chat-template helpers ─────────────────────────────────────────────────────

static bool is_llama3_model(const std::string& purpose_key) {
    std::string path = get_model_path_for_purpose(purpose_key);
    std::string lc = path;
    std::transform(lc.begin(), lc.end(), lc.begin(), ::tolower);
    return lc.find("llama") != std::string::npos ||
           lc.find("meta-") != std::string::npos;
}

// Llama-3 / Llama-3.1 instruct format.
// The template already includes the BOS token text so callers must pass
// add_bos=false to generate_text to avoid prepending it a second time.
static std::string apply_llama3_template(const std::vector<Message>& messages) {
    std::string out = "<|begin_of_text|>";
    for (const auto& m : messages) {
        out += "<|start_header_id|>" + m.role + "<|end_header_id|>\n\n"
             + m.content + "<|eot_id|>";
    }
    // Prime the model to generate the assistant turn
    out += "<|start_header_id|>assistant<|end_header_id|>\n\n";
    return out;
}

// Mistral Instruct v0.2 format.
// System content is injected into the first user turn.
// The template already includes <s> (BOS) so add_bos=false must be used.
static std::string apply_mistral_template(const std::vector<Message>& messages) {
    std::string out = "<s>";
    std::string pending_system;
    bool first_user = true;

    for (const auto& m : messages) {
        if (m.role == "system") {
            pending_system = m.content;
        } else if (m.role == "user") {
            std::string content = m.content;
            if (first_user && !pending_system.empty()) {
                content = pending_system + "\n\n" + content;
                pending_system.clear();
                first_user = false;
            }
            out += "[INST] " + content + " [/INST]";
        } else if (m.role == "assistant") {
            out += " " + m.content + "</s>";
        }
    }
    return out;
}

static std::string apply_chat_template(const std::vector<Message>& messages,
                                       const std::string& purpose_key) {
    return is_llama3_model(purpose_key)
        ? apply_llama3_template(messages)
        : apply_mistral_template(messages);
}

// ── Inference entry-points ────────────────────────────────────────────────────

// Max conversation turns kept in context to avoid "lost-in-the-middle" drift.
static const size_t MAX_HISTORY_TURNS = 12;

std::string run_inference_with_history(
    const std::string& prompt,
    const std::vector<std::pair<std::string, std::string>>& history,
    const std::string& purpose)
{
    if (get_service_mode() == ServiceMode::Embedding)
        return "Error: This instance is for embedding, not inference.";
    if (prompt.empty()) return "Error: Empty prompt";

    std::string purpose_key = normalize_purpose(purpose);
    ModelContext* mc = ensure_model_loaded(purpose_key);
    if (!mc) return "Error: Model failed to load for purpose='" + purpose_key + "'.";

    // Convert history + current prompt into a Messages list and apply the
    // correct chat template for the loaded model.
    std::vector<Message> messages;
    size_t start = (history.size() > MAX_HISTORY_TURNS)
                 ? history.size() - MAX_HISTORY_TURNS : 0;
    for (size_t i = start; i < history.size(); ++i) {
        messages.push_back({"user",      history[i].first});
        messages.push_back({"assistant", history[i].second});
    }
    messages.push_back({"user", prompt});

    std::string full_prompt = apply_chat_template(messages, purpose_key);
    if (full_prompt.length() > 65536) return "Error: Prompt too long (max 65536 characters)";

    const SamplingConfig& preset = (purpose_key == "summarization")
        ? SamplingPresets::BALANCED_0_1   // greedy → structured output (Mistral)
        : SamplingPresets::REASONING;     // near-greedy CoT → conversational (Llama)

    std::lock_guard<std::mutex> lock(g_inference_mutex);
    // add_bos=false: template already includes BOS (<|begin_of_text|> or <s>)
    return generate_text(mc, full_prompt, preset, /*add_bos=*/false);
}

std::string run_chat_completion(
    const std::vector<Message>& messages,
    const std::string& purpose,
    float temperature_override,
    int max_tokens_override)
{
    if (get_service_mode() == ServiceMode::Embedding)
        return "Error: This instance is for embedding, not inference.";
    if (messages.empty()) return "Error: No messages provided";

    std::string purpose_key = normalize_purpose(purpose);
    ModelContext* mc = ensure_model_loaded(purpose_key);
    if (!mc) return "Error: Model failed to load for purpose='" + purpose_key + "'.";

    std::string full_prompt = apply_chat_template(messages, purpose_key);
    if (full_prompt.length() > 65536) return "Error: Prompt too long (max 65536 characters)";

    SamplingConfig cfg = (purpose_key == "summarization")
        ? SamplingPresets::BALANCED_0_1   // greedy → structured output (Mistral)
        : SamplingPresets::REASONING;     // near-greedy CoT → conversational (Llama)

    if (temperature_override >= 0.0f) cfg.temperature  = temperature_override;
    if (max_tokens_override  >  0)    cfg.max_predict   = max_tokens_override;

    std::lock_guard<std::mutex> lock(g_inference_mutex);
    return generate_text(mc, full_prompt, cfg, /*add_bos=*/false);
}

std::vector<float> run_embed(const std::string& text) {
    if (get_service_mode() != ServiceMode::Embedding) return {};
    if (text.empty() || text.length() > 65536) return {};

    ModelContext* mc = ensure_model_loaded("summary");  // embedding mode has only one model
    if (!mc) return {};

    std::lock_guard<std::mutex> lock(g_inference_mutex);
    return get_embeddings(mc, text);
}

// ── Shutdown ──────────────────────────────────────────────────────────────────

void shutdown_inference() {
    std::lock_guard<std::mutex> lk(g_map_mutex);
    for (auto& kv : g_models) {
        if (!kv.second) continue;
        cleanup_model(kv.second);
        kv.second = nullptr;
    }
    g_models.clear();
    free_backend();
}
