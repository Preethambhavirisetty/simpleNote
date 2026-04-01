#include "model_loader.h"
#include "sampling_config.h"
#include <iostream>
#include <vector>
#include <mutex>
#include <thread>
#include <cmath>
#include <algorithm>
#include <random>
#include <limits>
#include <cstdlib>
#include <cstring>

static std::mutex g_context_mutex;
static std::once_flag g_backend_init_flag;
static bool g_backend_alive = false;

void init_backend() {
    std::call_once(g_backend_init_flag, [] {
        llama_backend_init();
        g_backend_alive = true;
    });
}

void free_backend() {
    if (g_backend_alive) {
        llama_backend_free();
        g_backend_alive = false;
    }
}

// ── Model loading ────────────────────────────────────────────────────────────

ModelContext* load_model(const std::string& model_path, const LoadOptions& opts) {
    init_backend();

    llama_model_params mparams = llama_model_default_params();
    mparams.use_mmap  = true;
    mparams.n_gpu_layers = opts.n_gpu_layers;
    mparams.main_gpu  = 0;
    mparams.vocab_only = false;

    llama_model* model = llama_model_load_from_file(model_path.c_str(), mparams);
    if (!model) {
        std::cerr << "Failed to load model from: " << model_path << "\n";
        return nullptr;
    }

    // Thread count: env LLAMA_N_THREADS → auto-detect physical cores → 4 floor.
    const char* env_threads = std::getenv("LLAMA_N_THREADS");
    int n_threads = (env_threads && env_threads[0]) ? std::atoi(env_threads) : 0;
    if (n_threads <= 0) {
        n_threads = static_cast<int>(std::thread::hardware_concurrency());
        if (n_threads <= 0) n_threads = 4;
    }

    llama_context_params cparams = llama_context_default_params();
    cparams.n_ctx      = opts.n_ctx;
    cparams.n_batch    = opts.embedding ? opts.n_ctx : std::min(2048, opts.n_ctx);
    cparams.n_threads  = n_threads;
    cparams.embeddings = opts.embedding;

    llama_context* ctx = llama_init_from_model(model, cparams);
    if (!ctx) {
        std::cerr << "Failed to create context\n";
        llama_model_free(model);
        return nullptr;
    }

    if (opts.embedding)
        llama_set_embeddings(ctx, true);

    return new ModelContext{model, ctx, cparams, opts.embedding};
}

// ── Context management ────────────────────────────────────────────────────────

static bool recreate_context(ModelContext* mc) {
    std::lock_guard<std::mutex> lock(g_context_mutex);
    if (mc->ctx) {
        llama_free(mc->ctx);
        mc->ctx = nullptr;
    }
    mc->ctx = llama_init_from_model(mc->model, mc->ctx_params);
    if (mc->ctx && mc->is_embedding)
        llama_set_embeddings(mc->ctx, true);
    return mc->ctx != nullptr;
}

// ── Text generation (internal) ────────────────────────────────────────────────
//
// Returns the generated text, or a string beginning with "Error:" on failure.
// `needs_recovery` is set to true when a decode failure leaves the context in a
// corrupt state that llama_memory_clear alone cannot fix.

static CompletionResult generate_text_impl(ModelContext* mc, const std::string& prompt,
                                           const SamplingConfig& config, bool add_bos,
                                           bool& needs_recovery) {
    needs_recovery = false;

    if (!mc || !mc->model || !mc->ctx) {
        std::cerr << "Invalid model context\n";
        return {"Error: Invalid model context", 0, 0};
    }

    std::string final_prompt = prompt;
    bool already_formatted =
        (prompt.find("[INST]")              != std::string::npos) ||
        (prompt.find("<|begin_of_text|>")   != std::string::npos) ||
        (prompt.find("<|start_header_id|>") != std::string::npos);

    if (!already_formatted) {
        final_prompt = "[INST] " + prompt + " [/INST]";
    }

    const llama_vocab* vocab = llama_model_get_vocab(mc->model);

    // parse_special must mirror add_bos:
    //   add_bos=false → caller provided a full chat template that embeds special
    //                   tokens as text (e.g. "<|eot_id|>"). We MUST parse them as
    //                   their single-token IDs so the model sees the correct format
    //                   and llama_vocab_is_eog() fires at the right point.
    //   add_bos=true  → plain/legacy prompt; no special-token strings to resolve.
    const bool parse_special = !add_bos;

    std::vector<llama_token> tokens(final_prompt.size() + 256);
    int n_tokens = llama_tokenize(
        vocab,
        final_prompt.c_str(),
        static_cast<int32_t>(final_prompt.size()),
        tokens.data(),
        static_cast<int32_t>(tokens.size()),
        add_bos,
        parse_special
    );

    if (n_tokens < 0) {
        tokens.resize(static_cast<size_t>(-n_tokens));
        n_tokens = llama_tokenize(
            vocab,
            final_prompt.c_str(),
            static_cast<int32_t>(final_prompt.size()),
            tokens.data(),
            static_cast<int32_t>(tokens.size()),
            add_bos,
            parse_special
        );
        if (n_tokens < 0) {
            std::cerr << "Tokenisation failed\n";
            return {"Error: Tokenisation failed", 0, 0};
        }
    }
    tokens.resize(static_cast<size_t>(n_tokens));

    // ── Prefill ──────────────────────────────────────────────────────────────
    const int n_ctx = static_cast<int>(mc->ctx_params.n_ctx);
    const int max_prompt_tokens = n_ctx - 1;

    if (n_tokens > max_prompt_tokens) {
        std::cerr << "Prompt too long (" << n_tokens << " tokens > " << max_prompt_tokens
                  << "); truncating to last " << max_prompt_tokens << " tokens.\n";
        int offset = n_tokens - max_prompt_tokens;
        tokens.erase(tokens.begin(), tokens.begin() + offset);
        n_tokens = max_prompt_tokens;
    }

    const int batch_cap = n_ctx;
    llama_batch batch = llama_batch_init(batch_cap, 0, 1);

    for (int i = 0; i < n_tokens; i++) {
        batch.token  [batch.n_tokens] = tokens[i];
        batch.pos    [batch.n_tokens] = i;
        batch.n_seq_id[batch.n_tokens] = 1;
        batch.seq_id [batch.n_tokens][0] = 0;
        batch.logits [batch.n_tokens] = false;
        batch.n_tokens++;
    }
    if (batch.n_tokens > 0)
        batch.logits[batch.n_tokens - 1] = true;

    if (llama_decode(mc->ctx, batch) != 0) {
        std::cerr << "Prefill decode failed (n_tokens=" << n_tokens << ")\n";
        llama_batch_free(batch);
        needs_recovery = true;
        return {"Error: Failed to decode prompt", n_tokens, 0};
    }

    // ── Sampling & generation loop ───────────────────────────────────────────
    std::string output;
    int n_cur = n_tokens;
    const int generation_limit = std::min(config.max_predict, n_ctx - n_tokens - 1);

    std::vector<llama_token> recent_tokens;
    if (config.repeat_last_n > 0)
        recent_tokens.reserve(static_cast<size_t>(config.repeat_last_n));

    const int n_vocab = static_cast<int>(llama_vocab_n_tokens(vocab));

    for (int i = 0; i < generation_limit; i++) {
        float* logits = llama_get_logits_ith(mc->ctx, batch.n_tokens - 1);
        if (!logits) {
            std::cerr << "Failed to get logits at step " << i << "\n";
            needs_recovery = true;
            break;
        }

        llama_token id = 0;

        if (config.temperature <= 0.01f) {
            id = 0;
            float max_logit = logits[0];
            for (int j = 1; j < n_vocab; j++) {
                if (logits[j] > max_logit) { max_logit = logits[j]; id = j; }
            }
        } else {
            std::vector<float> adj(logits, logits + n_vocab);

            if (config.repetition_penalty != 1.0f && !recent_tokens.empty()) {
                for (llama_token tok : recent_tokens) {
                    if (tok >= 0 && tok < n_vocab) {
                        float& l = adj[tok];
                        l = (l < 0.0f) ? l * config.repetition_penalty
                                       : l / config.repetition_penalty;
                    }
                }
            }

            std::vector<float> tl(n_vocab);
            for (int j = 0; j < n_vocab; j++)
                tl[j] = adj[j] / config.temperature;

            if (config.top_k > 0 && config.top_k < n_vocab) {
                std::vector<std::pair<float, int>> lx;
                lx.reserve(n_vocab);
                for (int j = 0; j < n_vocab; j++) lx.push_back({tl[j], j});
                std::sort(lx.begin(), lx.end(),
                          [](const auto& a, const auto& b) { return a.first > b.first; });
                for (int j = config.top_k; j < n_vocab; j++)
                    tl[lx[j].second] = -std::numeric_limits<float>::infinity();
            }

            float max_tl = *std::max_element(tl.begin(), tl.end());
            std::vector<float> probs(n_vocab);
            float sum = 0.0f;
            for (int j = 0; j < n_vocab; j++) {
                probs[j] = std::exp(tl[j] - max_tl);
                sum += probs[j];
            }
            if (sum > 0.0f)
                for (int j = 0; j < n_vocab; j++) probs[j] /= sum;

            if (config.top_p < 1.0f) {
                std::vector<std::pair<float, int>> px;
                px.reserve(n_vocab);
                for (int j = 0; j < n_vocab; j++)
                    if (probs[j] > 0.0f) px.push_back({probs[j], j});
                std::sort(px.begin(), px.end(),
                          [](const auto& a, const auto& b) { return a.first > b.first; });

                float cumsum = 0.0f;
                size_t cutoff = px.size();
                for (size_t j = 0; j < px.size(); j++) {
                    cumsum += px[j].first;
                    if (cumsum >= config.top_p) { cutoff = j + 1; break; }
                }
                for (size_t j = cutoff; j < px.size(); j++)
                    probs[px[j].second] = 0.0f;

                sum = 0.0f;
                for (int j = 0; j < n_vocab; j++) sum += probs[j];
                if (sum > 0.0f)
                    for (int j = 0; j < n_vocab; j++) probs[j] /= sum;
            }

            static thread_local std::mt19937 rng(std::random_device{}());
            float r = std::uniform_real_distribution<float>(0.0f, 1.0f)(rng);
            float cumsum = 0.0f;
            int fallback_id = 0;
            float fallback_prob = -1.0f;
            bool sampled = false;
            for (int j = 0; j < n_vocab; j++) {
                if (probs[j] > fallback_prob) { fallback_prob = probs[j]; fallback_id = j; }
                cumsum += probs[j];
                if (!sampled && r <= cumsum) { id = j; sampled = true; }
            }
            if (!sampled) id = fallback_id;
        }

        if (config.repeat_last_n > 0) {
            recent_tokens.push_back(id);
            if (recent_tokens.size() > static_cast<size_t>(config.repeat_last_n))
                recent_tokens.erase(recent_tokens.begin());
        }

        if (llama_vocab_is_eog(vocab, id))
            break;

        char buf[256];
        int n = llama_token_to_piece(vocab, id, buf, static_cast<int32_t>(sizeof(buf)), 0, false);
        if (n > 0 && n < static_cast<int>(sizeof(buf)))
            output.append(buf, static_cast<size_t>(n));

        batch.n_tokens = 0;
        batch.token  [0] = id;
        batch.pos    [0] = n_cur;
        batch.n_seq_id[0] = 1;
        batch.seq_id [0][0] = 0;
        batch.logits [0] = true;
        batch.n_tokens = 1;
        n_cur++;

        if (llama_decode(mc->ctx, batch) != 0) {
            std::cerr << "Decode failed at step " << i
                      << " (n_cur=" << n_cur << "/" << n_ctx << ")\n";
            needs_recovery = true;
            break;
        }
    }

    int completion_tokens = n_cur - n_tokens;
    llama_batch_free(batch);

    size_t s = output.find_first_not_of(" \t\n\r");
    if (s == std::string::npos) return {"", n_tokens, 0};
    size_t e = output.find_last_not_of(" \t\n\r");
    return {output.substr(s, e - s + 1), n_tokens, completion_tokens};
}

// ── Public entry point with automatic recovery ──────────────────────────────

CompletionResult generate_text(ModelContext* mc, const std::string& prompt,
                               const SamplingConfig& config, bool add_bos) {
    llama_memory_clear(llama_get_memory(mc->ctx), true);

    bool needs_recovery = false;
    CompletionResult result = generate_text_impl(mc, prompt, config, add_bos, needs_recovery);

    if (needs_recovery) {
        std::cerr << "Context corrupted — recreating (one-time recovery)...\n";
        if (!recreate_context(mc)) {
            std::cerr << "Fatal: could not recreate context\n";
            return result;
        }
        needs_recovery = false;
        result = generate_text_impl(mc, prompt, config, add_bos, needs_recovery);
        if (needs_recovery) {
            std::cerr << "Decode still failing after context recovery\n";
        }
    }

    return result;
}

// ── Embeddings ────────────────────────────────────────────────────────────────

std::vector<float> get_embeddings(ModelContext* mc, const std::string& text) {
    std::vector<float> out;
    if (!mc || !mc->model || !mc->ctx || !mc->is_embedding) return out;

    std::lock_guard<std::mutex> lock(g_context_mutex);
    llama_memory_clear(llama_get_memory(mc->ctx), true);

    const llama_vocab* vocab = llama_model_get_vocab(mc->model);
    std::vector<llama_token> tokens(text.size() + 256);
    int n_tokens = llama_tokenize(vocab, text.c_str(),
                                  static_cast<int32_t>(text.size()),
                                  tokens.data(),
                                  static_cast<int32_t>(tokens.size()),
                                  true, false);
    if (n_tokens < 0) {
        tokens.resize(static_cast<size_t>(-n_tokens));
        n_tokens = llama_tokenize(vocab, text.c_str(),
                                  static_cast<int32_t>(text.size()),
                                  tokens.data(),
                                  static_cast<int32_t>(tokens.size()),
                                  true, false);
    }
    if (n_tokens <= 0) return out;

    tokens.resize(static_cast<size_t>(n_tokens));
    llama_batch batch = llama_batch_init(n_tokens, 0, 1);
    for (int i = 0; i < n_tokens; i++) {
        batch.token  [i] = tokens[i];
        batch.pos    [i] = i;
        batch.n_seq_id[i] = 1;
        batch.seq_id [i][0] = 0;
        batch.logits [i] = (i == n_tokens - 1);
        batch.n_tokens++;
    }

    if (llama_decode(mc->ctx, batch) != 0) {
        llama_batch_free(batch);
        return out;
    }

    const int n_embd = llama_model_n_embd_out(mc->model);
    const float* emb = llama_get_embeddings_ith(mc->ctx, -1);
    if (emb && n_embd > 0)
        out.assign(emb, emb + n_embd);

    llama_batch_free(batch);
    return out;
}

// ── Cleanup ───────────────────────────────────────────────────────────────────

void cleanup_model(ModelContext* mc) {
    if (!mc) return;
    if (mc->ctx)   llama_free(mc->ctx);
    if (mc->model) llama_model_free(mc->model);
    delete mc;
}
