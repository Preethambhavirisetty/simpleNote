#include "run_inference.h"
#include "model_loader.h"
#include "sampling_config.h"
#include "service_config.h"
#include <cstdlib>
#include <iostream>
#include <map>
#include <mutex>
#include <string>

static void llama_log_callback_suppress(ggml_log_level, const char*, void*) {}

void suppress_llama_internal_logs() {
    llama_log_set(llama_log_callback_suppress, nullptr);
}

static const char* DEFAULT_PATH_SUMMARY = "/Users/rbhaviri/Desktop/_others/simpleNote/v2/notelite_inference/models/mistral_7b_instruct_v0_2_Q5_K_M.gguf";
static const char* DEFAULT_PATH_QUERY_PARSING = "/Users/rbhaviri/Desktop/_others/simpleNote/v2/notelite_inference/models/Phi_3_5_mini_instruct_Q5_K_M.gguf";

static std::map<std::string, ModelContext*> g_models;
static std::mutex g_map_mutex;
static std::mutex g_inference_mutex;

static std::string get_model_path_for_purpose(const std::string& purpose) {
    if (purpose == "query_parsing") {
        const char* env = std::getenv("MODEL_PURPOSE_QUERY_PARSING");
        if (env && env[0]) return env;
        return DEFAULT_PATH_QUERY_PARSING;
    }
    if (purpose == "summary") {
        const char* env = std::getenv("MODEL_PURPOSE_SUMMARY");
        if (env && env[0]) return env;
        return DEFAULT_PATH_SUMMARY;
    }
    /* default or unknown: use LLAMA_MODEL_PATH so one env fits all */
    const char* env = std::getenv("LLAMA_MODEL_PATH");
    if (env && env[0]) return env;
    return DEFAULT_PATH_SUMMARY;
}

static std::string normalize_purpose(const std::string& purpose) {
    if (purpose.empty()) return "default";
    return purpose;
}

static ModelContext* ensure_model_loaded(const std::string& purpose_key) {
    {
        std::lock_guard<std::mutex> lock(g_map_mutex);
        auto it = g_models.find(purpose_key);
        if (it != g_models.end() && it->second != nullptr)
            return it->second;
    }
    std::string path = get_model_path_for_purpose(purpose_key);
    std::cout << "Loading model for purpose='" << purpose_key << "' from " << path << "\n";
    LoadOptions opts;
    opts.embedding = (get_service_mode() == ServiceMode::Embedding);
    opts.n_ctx = opts.embedding ? 4096 : 32768;
    ModelContext* mc = load_model(path, opts);
    if (!mc) {
        std::cerr << "Model loading failed for purpose='" << purpose_key << "'\n";
        return nullptr;
    }
    std::lock_guard<std::mutex> lock(g_map_mutex);
    auto it = g_models.find(purpose_key);
    if (it != g_models.end()) {
        cleanup_model(mc);
        return it->second;
    }
    g_models[purpose_key] = mc;
    std::cout << "Model loaded (purpose=" << purpose_key << ").\n";
    return mc;
}

// Keep only the last N turns to reduce "lost in the middle" (model attends poorly to distant context)
static const size_t MAX_HISTORY_TURNS = 16;

static std::string build_prompt_with_history(const std::string& prompt, const std::vector<std::pair<std::string, std::string>>& history) {
    // Trim to last N turns so key context isn't buried in a long middle
    size_t start = (history.size() > MAX_HISTORY_TURNS) ? history.size() - MAX_HISTORY_TURNS : 0;

    std::string out = "Answer using only the conversation below. Do not invent or assume facts.\n\n";
    for (size_t i = start; i < history.size(); ++i) {
        const auto& p = history[i];
        out += "[INST] " + p.first + " [/INST] " + p.second + "\n\n";
    }
    out += "[INST] " + prompt + " [/INST]";
    return out;
}

std::string run_inference_with_history(const std::string& prompt, const std::vector<std::pair<std::string, std::string>>& history, const std::string& purpose) {
    if (get_service_mode() == ServiceMode::Embedding) return "Error: This instance is for embedding, not inference.";
    if (prompt.empty()) return "Error: Empty prompt";
    const std::string full_prompt = history.empty() ? prompt : build_prompt_with_history(prompt, history);
    if (full_prompt.length() > 65536) return "Error: Prompt too long (max 65536 characters)";

    std::string purpose_key = normalize_purpose(purpose);
    ModelContext* mc = ensure_model_loaded(purpose_key);
    if (!mc) return "Error: Model failed to load for purpose='" + purpose_key + "'.";

    const SamplingConfig& preset = (purpose_key == "query_parsing")
        ? SamplingPresets::BALANCED_0_1   // query_parsing: lower temp, more deterministic
        : SamplingPresets::BALANCED_0;   // summary / default: slightly higher temp
    std::lock_guard<std::mutex> lock(g_inference_mutex);
    return generate_text(mc, full_prompt, preset);
}

std::vector<float> run_embed(const std::string& text) {
    if (get_service_mode() != ServiceMode::Embedding) return {};
    if (text.empty()) return {};
    if (text.length() > 65536) return {};

    ModelContext* mc = ensure_model_loaded("default");
    if (!mc) return {};

    std::lock_guard<std::mutex> lock(g_inference_mutex);
    return get_embeddings(mc, text);
}

void shutdown_inference() {
    std::lock_guard<std::mutex> lock(g_map_mutex);
    bool first = true;
    for (auto& kv : g_models) {
        if (kv.second) {
            if (first) {
                cleanup_model(kv.second);
                first = false;
            } else {
                if (kv.second->ctx) llama_free(kv.second->ctx);
                if (kv.second->model) llama_model_free(kv.second->model);
                delete kv.second;
            }
            kv.second = nullptr;
        }
    }
    g_models.clear();
}