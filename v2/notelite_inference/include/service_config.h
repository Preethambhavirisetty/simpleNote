#pragma once
#include <string>

enum class ServiceMode { Summarization, Embedding };

// Set from main after parsing argv; used by routes and run_*.
void set_service_config(ServiceMode mode, const std::string& api_key);
ServiceMode get_service_mode();
const std::string& get_api_key();
bool require_api_key();  // true if api_key was set (auth required)
