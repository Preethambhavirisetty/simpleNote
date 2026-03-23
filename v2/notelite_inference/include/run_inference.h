#pragma once
#include <string>
#include <vector>

struct Message {
    std::string role;    // "system" | "user" | "assistant"
    std::string content;
};

void suppress_llama_internal_logs();

// Legacy API: kept for backward compat (converts to Messages internally).
std::string run_inference_with_history(
    const std::string& prompt,
    const std::vector<std::pair<std::string, std::string>>& history,
    const std::string& purpose
);

// Primary API: OpenAI-style chat completion.
// temperature_override < 0  → use preset default.
// max_tokens_override   <= 0 → use preset default.
std::string run_chat_completion(
    const std::vector<Message>& messages,
    const std::string& purpose,
    float temperature_override,
    int max_tokens_override
);

std::vector<float> run_embed(const std::string& text);
void shutdown_inference();
