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

// ── Log suppression ───────────────────────────────────────────────────────────

static void llama_log_callback_suppress(ggml_log_level, const char*, void*) {}

void suppress_llama_internal_logs() {
    llama_log_set(llama_log_callback_suppress, nullptr);
}

// ── Model paths ───────────────────────────────────────────────────────────────
//   Two models live in notelite_inference/models/:
//     • Meta-Llama-3.1-8B-Instruct-Q5_K_M.gguf  → primary reasoning / summarisation
//     • mistral_7b_instruct_v0_2_Q5_K_M.gguf     → intent classification / query parsing
//
//   Override at runtime with env vars:
//     MODEL_PURPOSE_SUMMARY        → path for reasoning model
//     MODEL_PURPOSE_QUERY_PARSING  → path for intent model
//     LLAMA_MODEL_PATH             → single-model fallback

static const char* DEFAULT_PATH_SUMMARY =
    "/Users/rbhaviri/Desktop/_others/simpleNote/v2/notelite_inference/models/"
    "Meta-Llama-3.1-8B-Instruct-Q5_K_M.gguf";

static const char* DEFAULT_PATH_QUERY_PARSING =
    "/Users/rbhaviri/Desktop/_others/simpleNote/v2/notelite_inference/models/"
    "mistral_7b_instruct_v0_2_Q5_K_M.gguf";

static std::string get_model_path_for_purpose(const std::string& purpose) {
    if (purpose == "query_parsing") {
        const char* env = std::getenv("MODEL_PURPOSE_QUERY_PARSING");
        if (env && env[0]) return env;
        return DEFAULT_PATH_QUERY_PARSING;
    }
    // "summary", "default", or anything else → reasoning model
    const char* env = std::getenv("MODEL_PURPOSE_SUMMARY");
    if (env && env[0]) return env;
    // Single-model override
    const char* gen = std::getenv("LLAMA_MODEL_PATH");
    if (gen && gen[0]) return gen;
    return DEFAULT_PATH_SUMMARY;
}

static std::string normalize_purpose(const std::string& purpose) {
    if (purpose.empty() || purpose == "default") return "summary";
    return purpose;
}

// ── Lazy-loading model registry ───────────────────────────────────────────────

static std::map<std::string, ModelContext*> g_models;
static std::mutex g_map_mutex;
static std::mutex g_inference_mutex;

static ModelContext* ensure_model_loaded(const std::string& purpose_key) {
    {
        std::lock_guard<std::mutex> lk(g_map_mutex);
        auto it = g_models.find(purpose_key);
        if (it != g_models.end() && it->second) return it->second;
    }

    std::string path = get_model_path_for_purpose(purpose_key);
    std::cout << "Loading model for purpose='" << purpose_key << "' from " << path << "\n";

    LoadOptions opts;
    opts.embedding = (get_service_mode() == ServiceMode::Embedding);
    opts.n_ctx     = opts.embedding ? 4096 : 32768;

    ModelContext* mc = load_model(path, opts);
    if (!mc) {
        std::cerr << "Model loading failed for purpose='" << purpose_key << "'\n";
        return nullptr;
    }

    std::lock_guard<std::mutex> lk(g_map_mutex);
    auto it = g_models.find(purpose_key);
    if (it != g_models.end() && it->second) {
        // Another thread already loaded it while we were loading — discard ours.
        cleanup_model(mc);
        return it->second;
    }
    g_models[purpose_key] = mc;
    std::cout << "Model loaded (purpose=" << purpose_key << ").\n";
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

    const SamplingConfig& preset = (purpose_key == "query_parsing")
        ? SamplingPresets::BALANCED_0_1
        : SamplingPresets::REASONING;

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

    // Start from the preset; selectively override with caller-supplied params.
    SamplingConfig cfg = (purpose_key == "query_parsing")
        ? SamplingPresets::BALANCED_0_1   // greedy → structured JSON / intent
        : SamplingPresets::REASONING;     // near-greedy CoT → Llama reasoning

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
    bool first = true;
    for (auto& kv : g_models) {
        if (!kv.second) continue;
        if (first) {
            cleanup_model(kv.second);  // also calls llama_backend_free()
            first = false;
        } else {
            if (kv.second->ctx)   llama_free(kv.second->ctx);
            if (kv.second->model) llama_model_free(kv.second->model);
            delete kv.second;
        }
        kv.second = nullptr;
    }
    g_models.clear();
}
