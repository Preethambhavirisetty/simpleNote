#pragma once
#include "cpp-httplib/httplib.h"
#include <string>
#include "service_config.h"

void register_routes(httplib::Server& svr, ServiceMode mode, const std::string& api_key);