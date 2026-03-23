#include "service_config.h"

static ServiceMode g_mode = ServiceMode::Summarization;
static std::string g_api_key;

void set_service_config(ServiceMode mode, const std::string& api_key) {
    g_mode = mode;
    g_api_key = api_key;
}

ServiceMode get_service_mode() { return g_mode; }
const std::string& get_api_key() { return g_api_key; }
bool require_api_key() { return !g_api_key.empty(); }
