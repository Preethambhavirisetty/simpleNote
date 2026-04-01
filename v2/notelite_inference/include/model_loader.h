#pragma once
#include <string>
#include <vector>
#include "llama.h"
#include "sampling_config.h"

struct LoadOptions {
    bool embedding    = false;
    int  n_ctx        = 4096;
    int  n_gpu_layers = 999;   // 999 = offload all; reduce when running multiple models
};

struct ModelContext {
    llama_model* model;
    llama_context* ctx;
    llama_context_params ctx_params;
    bool is_embedding = false;
};

void init_backend();
void free_backend();

ModelContext* load_model(const std::string& model_path, const LoadOptions& opts = LoadOptions{});

// add_bos: pass false when the prompt already includes a BOS token via a chat template
//          (e.g. <|begin_of_text|> for Llama-3 or <s> for Mistral).
std::string generate_text(ModelContext* ctx, const std::string& prompt,
                          const SamplingConfig& config, bool add_bos = true);

std::vector<float> get_embeddings(ModelContext* mc, const std::string& text);
void cleanup_model(ModelContext* mc);