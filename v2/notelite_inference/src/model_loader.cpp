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

// ── Model loading ────────────────────────────────────────────────────────────

ModelContext* load_model(const std::string& model_path, const LoadOptions& opts) {
    llama_backend_init();

    llama_model_params mparams = llama_model_default_params();
    mparams.use_mmap  = true;
    mparams.n_gpu_layers = 999;  // offload all layers; falls back to CPU gracefully
    mparams.main_gpu  = 0;
    mparams.vocab_only = false;

    llama_model* model = llama_model_load_from_file(model_path.c_str(), mparams);
    if (!model) {
        std::cerr << "Failed to load model from: " << model_path << "\n";
        llama_backend_free();
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
        llama_backend_free();
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

// ── Text generation ───────────────────────────────────────────────────────────

std::string generate_text(ModelContext* mc, const std::string& prompt,
                          const SamplingConfig& config, bool add_bos) {
    if (!mc || !mc->model || !mc->ctx) {
        std::cerr << "Invalid model context\n";
        return "Error: Invalid model context";
    }

    // Clear KV cache and recreate context to give each request a clean slate.
    if (!recreate_context(mc)) {
        std::cerr << "Failed to recreate context\n";
        return "Error: Failed to reset context";
    }

    // If the caller hasn't applied a chat template, wrap with a minimal one so
    // the model at least sees instruction markers.  Templates that already embed
    // BOS (Llama-3 or Mistral) are detected here so we never double-wrap.
    std::string final_prompt = prompt;
    bool already_formatted =
        (prompt.find("[INST]")              != std::string::npos) ||
        (prompt.find("<|begin_of_text|>")   != std::string::npos) ||
        (prompt.find("<|start_header_id|>") != std::string::npos);

    if (!already_formatted) {
        final_prompt = "[INST] " + prompt + " [/INST]";
    }

    const llama_vocab* vocab = llama_model_get_vocab(mc->model);

    // ── Tokenise ──────────────────────────────────────────────────────────────
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
            return "Error: Tokenisation failed";
        }
    }
    tokens.resize(static_cast<size_t>(n_tokens));

    // ── Prefill (batch-decode all prompt tokens) ───────────────────────────────
    const int batch_cap = static_cast<int>(mc->ctx_params.n_ctx);
    llama_batch batch   = llama_batch_init(batch_cap, 0, 1);

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
        std::cerr << "Failed to decode prompt\n";
        llama_batch_free(batch);
        return "Error: Failed to decode prompt";
    }

    // ── Sampling & generation loop ────────────────────────────────────────────
    std::string output;
    int n_cur     = n_tokens;
    int n_predict = config.max_predict;
    int min_tokens = config.min_tokens;

    std::vector<llama_token> recent_tokens;
    if (config.repeat_last_n > 0)
        recent_tokens.reserve(static_cast<size_t>(config.repeat_last_n));

    const int n_vocab = static_cast<int>(llama_vocab_n_tokens(vocab));

    for (int i = 0; i < n_predict; i++) {
        float* logits = llama_get_logits_ith(mc->ctx, batch.n_tokens - 1);
        if (!logits) {
            std::cerr << "Failed to get logits at step " << i << "\n";
            break;
        }

        llama_token id = 0;

        if (config.temperature <= 0.01f) {
            // ── Greedy ───────────────────────────────────────────────────────
            float max_logit = logits[0];
            for (int j = 1; j < n_vocab; j++) {
                if (logits[j] > max_logit) { max_logit = logits[j]; id = j; }
            }
        } else {
            // ── Sampled (temperature + repetition penalty + top-k + top-p) ──
            std::vector<float> adj(logits, logits + n_vocab);

            // Repetition penalty
            if (config.repetition_penalty != 1.0f && !recent_tokens.empty()) {
                for (llama_token tok : recent_tokens) {
                    if (tok >= 0 && tok < n_vocab) {
                        float& l = adj[tok];
                        l = (l < 0.0f) ? l * config.repetition_penalty
                                       : l / config.repetition_penalty;
                    }
                }
            }

            // Temperature scaling
            std::vector<float> tl(n_vocab);
            for (int j = 0; j < n_vocab; j++)
                tl[j] = adj[j] / config.temperature;

            // Top-k masking (before softmax for efficiency)
            if (config.top_k > 0 && config.top_k < n_vocab) {
                std::vector<std::pair<float, int>> lx;
                lx.reserve(n_vocab);
                for (int j = 0; j < n_vocab; j++) lx.push_back({tl[j], j});
                std::sort(lx.begin(), lx.end(),
                          [](const auto& a, const auto& b) { return a.first > b.first; });
                for (int j = config.top_k; j < n_vocab; j++)
                    tl[lx[j].second] = -std::numeric_limits<float>::infinity();
            }

            // Numerically-stable softmax: subtract max of *scaled* logits.
            float max_tl = *std::max_element(tl.begin(), tl.end());
            std::vector<float> probs(n_vocab);
            float sum = 0.0f;
            for (int j = 0; j < n_vocab; j++) {
                probs[j] = std::exp(tl[j] - max_tl);
                sum += probs[j];
            }
            if (sum > 0.0f)
                for (int j = 0; j < n_vocab; j++) probs[j] /= sum;

            // Top-p (nucleus) masking
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

                // Re-normalise after nucleus truncation
                sum = 0.0f;
                for (int j = 0; j < n_vocab; j++) sum += probs[j];
                if (sum > 0.0f)
                    for (int j = 0; j < n_vocab; j++) probs[j] /= sum;
            }

            // Sample from the final distribution
            static thread_local std::mt19937 rng(std::random_device{}());
            float r = std::uniform_real_distribution<float>(0.0f, 1.0f)(rng);
            float cumsum = 0.0f;
            for (int j = 0; j < n_vocab; j++) {
                cumsum += probs[j];
                if (r <= cumsum) { id = j; break; }
            }
        }

        // Track recent tokens for repetition penalty
        if (config.repeat_last_n > 0) {
            recent_tokens.push_back(id);
            if (recent_tokens.size() > static_cast<size_t>(config.repeat_last_n))
                recent_tokens.erase(recent_tokens.begin());
        }

        // ① EOG check BEFORE text conversion: <|eot_id|>, <|end_of_text|>, EOS, etc.
        //   With parse_special=true these fire as real token IDs, not text.
        //   We break unconditionally — the model only emits EOG when it is done.
        if (llama_vocab_is_eog(vocab, id))
            break;

        // ② Convert token ID → UTF-8 (special=false → control tokens return empty)
        char buf[256];
        int n = llama_token_to_piece(vocab, id, buf, static_cast<int32_t>(sizeof(buf)), 0, false);
        if (n > 0 && n < static_cast<int>(sizeof(buf)))
            output.append(buf, static_cast<size_t>(n));

        // Next-token batch
        batch.n_tokens = 0;
        batch.token  [0] = id;
        batch.pos    [0] = n_cur;
        batch.n_seq_id[0] = 1;
        batch.seq_id [0][0] = 0;
        batch.logits [0] = true;
        batch.n_tokens = 1;
        n_cur++;

        if (llama_decode(mc->ctx, batch) != 0) {
            std::cerr << "Decode failed at step " << i << "\n";
            break;
        }
    }

    llama_batch_free(batch);

    // Trim leading/trailing whitespace that Llama-3 sometimes prefixes.
    size_t s = output.find_first_not_of(" \t\n\r");
    if (s == std::string::npos) return "";
    size_t e = output.find_last_not_of(" \t\n\r");
    return output.substr(s, e - s + 1);
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
    llama_backend_free();
}
