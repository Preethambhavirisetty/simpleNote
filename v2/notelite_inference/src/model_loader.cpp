#include "model_loader.h"
#include "sampling_config.h"
#include <iostream>
#include <vector>
#include <mutex>
#include <cmath>
#include <algorithm>
#include <random>
#include <limits>

// Global mutex to protect context operations
static std::mutex g_context_mutex;

ModelContext* load_model(const std::string& model_path, const LoadOptions& opts) {
    llama_backend_init();

    llama_model_params mparams = llama_model_default_params();
    mparams.use_mmap = true;
    mparams.n_gpu_layers = 999;
    mparams.main_gpu = 0;
    mparams.vocab_only = false;

    llama_model* model = llama_model_load_from_file(model_path.c_str(), mparams);
    if (!model) {
        std::cerr << "Failed to load model from: " << model_path << "\n";
        llama_backend_free();
        return nullptr;
    }

    llama_context_params cparams = llama_context_default_params();
    cparams.n_ctx = opts.n_ctx;
    // A100 80GB: large batch for long prompts and throughput
    cparams.n_batch = opts.embedding ? opts.n_ctx : std::min(8192, opts.n_ctx);
    cparams.n_threads = 30;
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

    auto* mc = new ModelContext{model, ctx, cparams, opts.embedding};
    return mc;
}

static bool recreate_context(ModelContext* mc) {
    std::lock_guard<std::mutex> lock(g_context_mutex);
    
    // mc->ctx: mc is a pointer to ModelContext object which accesses its member ctx
    if (mc->ctx) {
        llama_free(mc->ctx);
        mc->ctx = nullptr;
    }
    
    mc->ctx = llama_init_from_model(mc->model, mc->ctx_params);
    if (mc->ctx && mc->is_embedding)
        llama_set_embeddings(mc->ctx, true);
    return mc->ctx != nullptr;
}

std::string generate_text(ModelContext* mc, const std::string& prompt, const SamplingConfig& config) {
    if (!mc || !mc->model || !mc->ctx) {
        std::cerr << "Invalid model context\n";
        return "Error: Invalid model context";
    }

    if (!recreate_context(mc)) {
        std::cerr << "Failed to recreate context\n";
        return "Error: Failed to reset context";
    }

    // Use prompt as-is for Mistral Instruct - it has its own format
    std::string final_prompt = prompt;
    
    // Only add Mistral instruction format if not already present
    if (prompt.find("[INST]") == std::string::npos) {
        final_prompt = "[INST] " + prompt + " [/INST]";
    }

    const llama_vocab* vocab = llama_model_get_vocab(mc->model);

    // Tokenize
    std::vector<llama_token> tokens(final_prompt.size() + 256);
    int n_tokens = llama_tokenize(
        vocab,
        final_prompt.c_str(),
        final_prompt.size(),
        tokens.data(),
        tokens.size(),
        true,
        false
    );

    if (n_tokens < 0) {
        tokens.resize(-n_tokens);
        n_tokens = llama_tokenize(
            vocab,
            final_prompt.c_str(),
            final_prompt.size(),
            tokens.data(),
            tokens.size(),
            true,
            false
        );
        
        if (n_tokens < 0) {
            std::cerr << "Tokenization failed\n";
            return "Error: Tokenization failed";
        }
    }

    tokens.resize(n_tokens);

    // Batch sized to context (A100 80GB can handle full context in one go)
    const int batch_cap = static_cast<int>(mc->ctx_params.n_ctx);
    llama_batch batch = llama_batch_init(batch_cap, 0, 1);

    // Add tokens to batch
    for (int i = 0; i < n_tokens; i++) {
        batch.token[batch.n_tokens] = tokens[i];
        batch.pos[batch.n_tokens] = i;
        batch.n_seq_id[batch.n_tokens] = 1;
        batch.seq_id[batch.n_tokens][0] = 0;
        batch.logits[batch.n_tokens] = false;
        batch.n_tokens++;
    }

    if (batch.n_tokens > 0) {
        batch.logits[batch.n_tokens - 1] = true;
    }

    // Decode prompt
    if (llama_decode(mc->ctx, batch) != 0) {
        std::cerr << "Failed to decode prompt\n";
        llama_batch_free(batch);
        return "Error: Failed to decode prompt";
    }

    std::string output;
    int n_predict = config.max_predict;
    int n_cur = n_tokens;
    int min_tokens = config.min_tokens;
    
    std::vector<llama_token> recent_tokens;
    if (config.repeat_last_n > 0) {
        recent_tokens.reserve(config.repeat_last_n);
    }

    // Generation loop
    for (int i = 0; i < n_predict; i++) {
        float* logits = llama_get_logits_ith(mc->ctx, batch.n_tokens - 1);
        if (!logits) {
            std::cerr << "Failed to get logits at " << i << "\n";
            break;
        }

        int n_vocab = llama_vocab_n_tokens(vocab);
        llama_token id = 0;

        if (config.temperature <= 0.01f) {
            // Greedy sampling
            float max_logit = logits[0];
            for (int j = 1; j < n_vocab; j++) {
                if (logits[j] > max_logit) {
                    max_logit = logits[j];
                    id = j;
                }
            }
        } else {
            std::vector<float> adjusted_logits(logits, logits + n_vocab);

            if (config.repetition_penalty != 1.0f && !recent_tokens.empty()) {
                for (llama_token tok : recent_tokens) {
                    if (tok >= 0 && tok < n_vocab) {
                        if (adjusted_logits[tok] < 0)
                            adjusted_logits[tok] *= config.repetition_penalty;
                        else
                            adjusted_logits[tok] /= config.repetition_penalty;
                    }
                }
            }

            float max_logit = *std::max_element(adjusted_logits.begin(), adjusted_logits.end());
            std::vector<float> temp_logits(n_vocab);
            for (int j = 0; j < n_vocab; j++)
                temp_logits[j] = adjusted_logits[j] / config.temperature;

            if (config.top_k > 0 && config.top_k < n_vocab) {
                std::vector<std::pair<float, int>> logit_idx;
                logit_idx.reserve(n_vocab);
                for (int j = 0; j < n_vocab; j++) {
                    logit_idx.push_back({temp_logits[j], j});
                }
                
                std::sort(logit_idx.begin(), logit_idx.end(),
                    [](const auto& a, const auto& b) { return a.first > b.first; });
                for (int j = config.top_k; j < n_vocab; j++)
                    temp_logits[logit_idx[j].second] = -std::numeric_limits<float>::infinity();
            }

            // Softmax
            std::vector<float> probs(n_vocab);
            float sum = 0.0f;
            for (int j = 0; j < n_vocab; j++) {
                probs[j] = expf(temp_logits[j] - max_logit);
                sum += probs[j];
            }
            
            for (int j = 0; j < n_vocab; j++)
                probs[j] /= sum;

            if (config.top_p < 1.0f) {
                std::vector<std::pair<float, int>> prob_idx;
                for (int j = 0; j < n_vocab; j++) {
                    if (probs[j] > 0) {
                        prob_idx.push_back({probs[j], j});
                    }
                }
                
                std::sort(prob_idx.begin(), prob_idx.end(),
                    [](const auto& a, const auto& b) { return a.first > b.first; });
                float cumsum = 0.0f;
                size_t cutoff = prob_idx.size();
                for (size_t j = 0; j < prob_idx.size(); j++) {
                    cumsum += prob_idx[j].first;
                    if (cumsum >= config.top_p) {
                        cutoff = j + 1;
                        break;
                    }
                }
                
                for (size_t j = cutoff; j < prob_idx.size(); j++) {
                    probs[prob_idx[j].second] = 0.0f;
                }
                
                sum = 0.0f;
                for (int j = 0; j < n_vocab; j++) {
                    sum += probs[j];
                }
                if (sum > 0.0f) {
                    for (int j = 0; j < n_vocab; j++) {
                        probs[j] /= sum;
                    }
                }
            }

            static thread_local std::mt19937 rng(std::random_device{}());
            float r = std::uniform_real_distribution<float>(0.0f, 1.0f)(rng);
            float cumsum = 0.0f;
            for (int j = 0; j < n_vocab; j++) {
                cumsum += probs[j];
                if (r <= cumsum) {
                    id = j;
                    break;
                }
            }
        }

        // Track for repetition
        if (config.repeat_last_n > 0) {
            recent_tokens.push_back(id);
            if (recent_tokens.size() > static_cast<size_t>(config.repeat_last_n)) {
                recent_tokens.erase(recent_tokens.begin());
            }
        }

        // Convert token to text
        char buf[256];
        int n = llama_token_to_piece(vocab, id, buf, sizeof(buf), 0, false);
        if (n > 0 && n < sizeof(buf)) {
            output.append(buf, n);
        }

        if (llama_vocab_is_eog(vocab, id) && i >= min_tokens)
            break;

        // Prepare next batch
        batch.n_tokens = 0;
        batch.token[batch.n_tokens] = id;
        batch.pos[batch.n_tokens] = n_cur;
        batch.n_seq_id[batch.n_tokens] = 1;
        batch.seq_id[batch.n_tokens][0] = 0;
        batch.logits[batch.n_tokens] = true;
        batch.n_tokens++;
        n_cur++;

        if (llama_decode(mc->ctx, batch) != 0) {
            std::cerr << "Decode failed at " << i << "\n";
            break;
        }
    }

    llama_batch_free(batch);
    return output;
}

std::vector<float> get_embeddings(ModelContext* mc, const std::string& text) {
    std::vector<float> out;
    if (!mc || !mc->model || !mc->ctx || !mc->is_embedding) return out;

    std::lock_guard<std::mutex> lock(g_context_mutex);
    llama_memory_clear(llama_get_memory(mc->ctx), true);

    const llama_vocab* vocab = llama_model_get_vocab(mc->model);
    std::vector<llama_token> tokens(text.size() + 256);
    int n_tokens = llama_tokenize(vocab, text.c_str(), text.size(), tokens.data(), tokens.size(), true, false);
    if (n_tokens < 0) {
        tokens.resize(-n_tokens);
        n_tokens = llama_tokenize(vocab, text.c_str(), text.size(), tokens.data(), tokens.size(), true, false);
    }
    if (n_tokens <= 0) return out;

    tokens.resize(n_tokens);
    llama_batch batch = llama_batch_init(n_tokens, 0, 1);
    for (int i = 0; i < n_tokens; i++) {
        batch.token[batch.n_tokens] = tokens[i];
        batch.pos[batch.n_tokens] = i;
        batch.n_seq_id[batch.n_tokens] = 1;
        batch.seq_id[batch.n_tokens][0] = 0;
        batch.logits[batch.n_tokens] = (i == n_tokens - 1);
        batch.n_tokens++;
    }

    if (llama_decode(mc->ctx, batch) != 0) {
        llama_batch_free(batch);
        return out;
    }

    const int n_embd = llama_model_n_embd_out(mc->model);
    const float* emb = llama_get_embeddings_ith(mc->ctx, -1); // pointer to the array of floats
    if (emb && n_embd > 0) {
        out.assign(emb, emb + n_embd); // when n_embd is added, moves the emb pointer n_embd floats forward
    }
    llama_batch_free(batch);
    return out;
}

void cleanup_model(ModelContext* mc) {
    if (mc) {
        if (mc->ctx) llama_free(mc->ctx);
        if (mc->model) llama_model_free(mc->model);
        delete mc;
    }
    llama_backend_free();
}

