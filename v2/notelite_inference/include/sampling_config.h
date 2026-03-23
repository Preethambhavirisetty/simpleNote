#pragma once

// Advanced sampling configuration for improved text generation
struct SamplingConfig {
    // Core sampling parameters
    float temperature = 0.6f;        // Controls randomness (0.0 = deterministic, 1.0+ = more random)
    float top_p = 0.85f;             // Nucleus sampling threshold (0.1-0.9, higher = more diverse)
    int top_k = 50;                  // Top-k sampling (10-100, lower = more focused)
    
    // Repetition control
    float repetition_penalty = 1.1f; // Penalty for repeated tokens (1.0 = no penalty, 1.3+ = strong penalty)
    int repeat_last_n = -1;          // Number of recent tokens to consider for repetition penalty. -1 means no repetition penalty.
    
    // Generation limits
    int min_tokens = 500;             // Minimum tokens to generate
    int max_tokens = 300;            // Maximum tokens to prevent rambling
    int max_predict = 4096;           // Hard limit on generation, larger is better for longer texts.
    
    // Stop sequences
    bool enable_stop_sequences = false; // Enable automatic stop sequence detection
    
    // Quality control
    bool enable_enhanced_prompting = false; // Add instruction formatting to prompts
};

// Default configuration for different use cases
namespace SamplingPresets {
    // Conservative - focused, coherent responses
    static const SamplingConfig CONSERVATIVE = {
        .temperature = 0.4f,
        .top_p = 0.8f,
        .top_k = 40,
        .repetition_penalty = 1.1f,
        .repeat_last_n = 4096,
        .min_tokens = 100,
        .max_tokens = 200,
        .max_predict = 256
    };
    
    // Balanced - good mix of creativity and coherence
    static const SamplingConfig BALANCED_0 = {
        .temperature = 0.4f,        // Lower for factual and accurate responses, suitable for summarization tasks
        .top_p = 0.9f,             // 0.85 = more focused, 0.9 = balanced, 0.95 = more diverse, 1 = consider all tokens
        .top_k = 50,               // 1 = greedy(always pick best), 40 = good variety, 50 = more options, 100 = too many options
        .repetition_penalty = 1.05f, // penalizes repeated tokens to avoid repetition; 1 = no penalty, 1.1 = mild penalty, 1.3 = heavy penalty(may harm quality)
        .repeat_last_n = 20,       // Look back 64 tokens
        .min_tokens = 20,          // Lower minimum to avoid forcing long outputs
        .max_tokens = 200,
        .max_predict = 512
    };

    // Reasoning (Llama-3.1-8B-Instruct) ─────────────────────────────────────
    // Near-deterministic for consistent step-by-step output.
    // No repetition penalty: reasoning naturally reuses key terms (penalising
    // them breaks logical chains).  Token budget is generous enough for CoT but
    // capped to avoid rambling.
    static const SamplingConfig REASONING = {
        .temperature = 0.15f,
        .top_p = 0.9f,
        .top_k = 0,              // top_p alone is sufficient at near-zero temp
        .repetition_penalty = 1.0f,
        .repeat_last_n = 0,
        .min_tokens = 0,
        .max_tokens = 1024,
        .max_predict = 1024
    };

    // For query_parsing: low temp for deterministic, structured output
    static const SamplingConfig BALANCED_0_1 = {
        .temperature = 0.0f,
        .top_p = 1.0f,
        .top_k = 0, 
        .repetition_penalty = 1.0f,
        .repeat_last_n = 0,
        .min_tokens = 0,
        .max_tokens = 256,
        .max_predict = 256
    };

    static const SamplingConfig BALANCED_1 = {
        .temperature = 0.6f,
        .top_p = 0.85f,
        .top_k = 50,
        .repetition_penalty = 1.1f,
        .repeat_last_n = 4096,
        .min_tokens = 100,
        .max_tokens = 300,
        .max_predict = 4096
    };
    
    // Creative - more diverse and creative responses
    static const SamplingConfig CREATIVE = {
        .temperature = 0.8f,
        .top_p = 0.9f,
        .top_k = 40,
        .repetition_penalty = 1.1f,
        .repeat_last_n = 4096,
        .min_tokens = 100,
        .max_tokens = 400,
        .max_predict = 4096
    };
    
    // Creative Writing - optimized for creative tasks like zombie sentences
    static const SamplingConfig CREATIVE_WRITING = {
        .temperature = 0.9f,        // High creativity
        .top_p = 0.95f,            // Very diverse
        .top_k = 30,               // Focused but creative
        .repetition_penalty = 1.3f, // Strong anti-repetition
        .repeat_last_n = 84,       // Look back 32 tokens
        .min_tokens = 20,          // Low minimum
        .max_tokens = 150,         // Reasonable for sentences
        .max_predict = 1024         // Short responses
    };
}
