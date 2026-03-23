#pragma once
#include <string>
#include <vector>
#include "llama.h"
#include "sampling_config.h"

struct LoadOptions {
    bool embedding = false;
    int n_ctx = 4096;
};

struct ModelContext {
    llama_model* model;
    llama_context* ctx;
    llama_context_params ctx_params;
    bool is_embedding = false;
};

ModelContext* load_model(const std::string& model_path, const LoadOptions& opts = LoadOptions{});
std::string generate_text(ModelContext* ctx, const std::string& prompt, const SamplingConfig& config);
std::vector<float> get_embeddings(ModelContext* mc, const std::string& text);
void cleanup_model(ModelContext* mc);