#include <iostream>
#include <csignal>
#include <cstdlib>
#include <cstring>
#include "register_routes.h"
#include "run_inference.h"
#include "model_loader.h"
#include "service_config.h"

static void signal_handler(int) {
    std::cout << "\nShutting down...\n";
    shutdown_inference();
    std::exit(0);
}

static ServiceMode parse_mode(const char* val) {
    if (std::strcmp(val, "embedding") == 0) return ServiceMode::Embedding;
    // "summarization" and "chat" both serve /v1/chat/completions (text generation)
    return ServiceMode::Summarization;
}

static void parse_args(int argc, char** argv, ServiceMode& mode, std::string& api_key) {
    for (int i = 1; i < argc; i++) {
        const char* a = argv[i];
        if (std::strncmp(a, "--api-key=", 10) == 0) {
            api_key = a + 10;
        } else if (std::strcmp(a, "--api-key") == 0 && i + 1 < argc) {
            api_key = argv[++i];
        } else if (std::strncmp(a, "--mode=", 7) == 0) {
            mode = parse_mode(a + 7);
        } else if (std::strcmp(a, "--mode") == 0 && i + 1 < argc) {
            mode = parse_mode(argv[++i]);
        }
    }
    const char* env_mode = std::getenv("SERVICE_MODE");
    if (env_mode && env_mode[0])
        mode = parse_mode(env_mode);
}

int main(int argc, char** argv) {
    std::signal(SIGINT, signal_handler); // interruption signal 
    std::signal(SIGTERM, signal_handler); // termination signal
    // shutdown_inference function is automatically called when program exits 
    std::atexit(shutdown_inference);

    ServiceMode mode = ServiceMode::Summarization;
    std::string api_key;
    parse_args(argc, argv, mode, api_key);

    init_backend();
    suppress_llama_internal_logs();

    // Port: --port=N  |  PORT env var  |  default 8081
    int port = 8081;
    for (int i = 1; i < argc; i++) {
        if (std::strncmp(argv[i], "--port=", 7) == 0) {
            port = std::atoi(argv[i] + 7);
        } else if (std::strcmp(argv[i], "--port") == 0 && i + 1 < argc) {
            port = std::atoi(argv[++i]);
        }
    }
    const char* env_port = std::getenv("PORT");
    if (env_port && env_port[0]) port = std::atoi(env_port);

    httplib::Server svr;
    register_routes(svr, mode, api_key);

    std::cout << "Server: http://0.0.0.0:" << port
              << " (mode=" << (mode == ServiceMode::Embedding ? "embedding" : "summarization") << ")\n";
    if (!svr.listen("0.0.0.0", port)) {
        std::cerr << "ERROR: Failed to bind to port " << port
                  << " — is another process using it?  (check: lsof -i :" << port << ")\n";
        return 1;
    }
    return 0;
}