#pragma once
#include <string>
#include <vector>

void suppress_llama_internal_logs();
std::string run_inference_with_history(const std::string& prompt, const std::vector<std::pair<std::string, std::string>>& history, const std::string& purpose);
std::vector<float> run_embed(const std::string& text);
void shutdown_inference();