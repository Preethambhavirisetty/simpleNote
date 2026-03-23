#include "register_routes.h"
#include "run_inference.h"
#include "service_config.h"
#include <iostream>
#include <sstream>
#include <vector>
#include <utility>

static std::string json_escape(const std::string& s) {
    std::ostringstream out;
    for (char c : s) {
        if (c == '"') out << "\\\"";
        else if (c == '\\') out << "\\\\";
        else if (c == '\n') out << "\\n";
        else if (c == '\r') out << "\\r";
        else if (static_cast<unsigned char>(c) >= 32) out << c;
    }
    return out.str();
}

// API key is optional: if not set, all requests pass. If set, client must send same secret (shared secret).
static bool check_auth(const httplib::Request& req, const std::string& api_key) {
    if (api_key.empty()) return true;  // no key configured -> no auth required
    std::string auth = req.get_header_value("Authorization");
    if (auth.size() > 7 && auth.compare(0, 7, "Bearer ") == 0 && auth.substr(7) == api_key)
        return true;
    return req.get_header_value("X-Api-Key") == api_key;
}

// Supports both: (1) plain text body = prompt only, no history; (2) JSON with "prompt" and optional "history".
static bool parse_infer_body(const std::string& body, std::string& prompt, std::vector<std::pair<std::string, std::string>>& history) {
    history.clear();
    if (body.empty()) return false;
    if (body[0] != '{') {
        prompt = body;  // plain text -> single prompt, no history
        return true;
    }
    size_t i = 0;
    auto skip_ws = [&]() { while (i < body.size() && (body[i] == ' ' || body[i] == '\t' || body[i] == '\n' || body[i] == '\r')) i++; };
    auto skip_comma_ws = [&]() {
        skip_ws();
        if (i < body.size() && body[i] == ',') { i++; skip_ws(); }
    };
    auto find_key = [&](const char* key) -> bool {
        skip_ws();
        size_t k = 0;
        while (key[k] && i + k < body.size() && body[i + k] == key[k]) k++;
        if (!key[k] && i + k < body.size()) { i += k; return true; }
        return false;
    };
    auto extract_string = [&]() -> std::string {
        skip_ws();
        if (i >= body.size() || body[i] != '"') return "";
        i++;
        std::string s;
        while (i < body.size()) {
            if (body[i] == '\\') { i++; if (i < body.size()) s += body[i++]; continue; }
            if (body[i] == '"') { i++; break; }
            s += body[i++];
        }
        return s;
    };

    i++; skip_ws();  // skip opening '{'
    if (!find_key("\"prompt\"")) return false;
    skip_ws();
    if (i >= body.size() || body[i] != ':') return false;
    i++;
    prompt = extract_string();
    if (prompt.empty() && i < body.size() && body[i] == 'n') {
        if (i + 4 <= body.size() && body.compare(i, 4, "null") == 0) { i += 4; prompt = ""; }
    }

    skip_comma_ws();  // skip comma after "prompt" value so we can find "history"
    if (!find_key("\"history\"")) return true;
    skip_ws();
    if (i >= body.size() || body[i] != ':') return true;
    i++;
    skip_ws();
    if (i >= body.size() || body[i] != '[') return true;
    i++;
    std::string last_user, last_assistant;
    while (i < body.size()) {
        skip_ws();
        if (body[i] == ']') { i++; break; }
        if (body[i] != '{') break;
        i++;
        std::string role, content;
        if (find_key("\"role\"")) { skip_ws(); if (body[i] == ':') i++; role = extract_string(); }
        skip_comma_ws();  // skip comma between "role" and "content"
        if (find_key("\"content\"")) { skip_ws(); if (body[i] == ':') i++; content = extract_string(); }
        if (role == "user") { last_user = content; }
        else if (role == "assistant") {
            last_assistant = content;
            if (!last_user.empty()) {
                history.push_back({ last_user, last_assistant });
                last_user.clear();
                last_assistant.clear();
            }
        }
        skip_ws();
        while (i < body.size() && body[i] != '}' && body[i] != ']') i++;
        if (i < body.size() && body[i] == '}') i++;
        skip_ws();
        if (i < body.size() && body[i] == ',') i++;
    }
    return true;
}

void register_routes(httplib::Server& svr, ServiceMode mode, const std::string& api_key) {
    set_service_config(mode, api_key); // CLEAR

    // c++ lambda function which uses api_key variable from the outside
    // syntax: const val = []() -> {...}
    auto auth = [api_key](const httplib::Request& req, httplib::Response& res) -> bool {
        if (!check_auth(req, api_key)) {
            res.status = 401;
            res.set_content("{\"error\":\"Missing or invalid API key\"}", "application/json");
            return false;
        }
        return true;
    };

    std::cout << "Registering routes (mode: " << (mode == ServiceMode::Embedding ? "embedding" : "summarization") << ")...\n";

    svr.Get("/ping", [](const httplib::Request&, httplib::Response& res) {
        res.set_content("pong", "text/plain");
    });

    svr.Get("/health", [](const httplib::Request&, httplib::Response& res) {
        res.set_content("{\"status\":\"ok\",\"service\":\"inference-api\"}", "application/json");
    });

    if (mode == ServiceMode::Embedding) {
        svr.Post("/embed", [auth, api_key](const httplib::Request& req, httplib::Response& res) {
            if (!auth(req, res)) return;
            if (req.body.empty()) {
                res.status = 400;
                res.set_content("{\"error\":\"Empty request body\"}", "application/json");
                std::cout << "POST /embed -> 400\n";
                return;
            }
            // no cap means a very long tokenization and one big forward pass.
            if (req.body.length() > 65536) {
                res.status = 413;
                res.set_content("{\"error\":\"Request too large (max 65536 characters)\"}", "application/json");
                std::cout << "POST /embed -> 413\n";
                return;
            }
            try {
                std::vector<float> emb = run_embed(req.body);
                if (emb.empty()) {
                    res.status = 500;
                    res.set_content("{\"error\":\"Embedding failed\"}", "application/json");
                    std::cout << "POST /embed -> 500\n";
                    return;
                }
                std::ostringstream json;
                json << "{\"embedding\":[";
                for (size_t i = 0; i < emb.size(); i++)
                    json << (i ? "," : "") << emb[i];
                json << "]}";
                res.set_content(json.str(), "application/json");
                std::cout << "POST /embed -> 200\n";
            } catch (const std::exception& e) {
                res.status = 500;
                res.set_content("{\"error\":\"" + json_escape(e.what()) + "\"}", "application/json");
                std::cout << "POST /embed -> 500\n";
            }
        });
    } else {
        svr.Post("/v1/chat/completions", [auth, api_key](const httplib::Request& req, httplib::Response& res) {
            if (!auth(req, res)) return;
            if (req.body.empty()) {
                res.status = 400;
                res.set_content("{\"error\":\"Empty request body\"}", "application/json");
                std::cout << "POST /v1/chat/completions -> 400 (empty body)\n";
                return;
            }
            if (req.body.length() > 65536) {
                res.status = 413;
                res.set_content("{\"error\":\"Request too large (max 65536 characters)\"}", "application/json");
                std::cout << "POST /v1/chat/completions -> 413 (too large)\n";
                return;
            }

            std::string prompt;
            std::vector<std::pair<std::string, std::string>> history;
            if (!parse_infer_body(req.body, prompt, history)) {
                res.status = 400;
                res.set_content("{\"error\":\"Invalid JSON: expected prompt\"}", "application/json");
                std::cout << "POST /v1/chat/completions -> 400 (bad JSON)\n";
                return;
            }
            std::string purpose = req.get_param_value("purpose");

            try {
                std::string output = run_inference_with_history(prompt, history, purpose);
                if (output.find("Error:") == 0) {
                    res.status = 500;
                    res.set_content("{\"error\":\"" + json_escape(output) + "\"}", "application/json");
                    std::cout << "POST /v1/chat/completions -> 500\n";
                } else {
                    res.set_content(output, "text/plain");
                    std::cout << "POST /v1/chat/completions -> 200\n";
                }
            } catch (const std::exception& e) {
                res.status = 500;
                res.set_content("{\"error\":\"Internal server error: " + json_escape(e.what()) + "\"}", "application/json");
                std::cout << "POST /v1/chat/completions -> 500 (exception)\n";
            } catch (...) {
                res.status = 500;
                res.set_content("{\"error\":\"Unknown internal error\"}", "application/json");
                std::cout << "POST /v1/chat/completions -> 500 (unknown)\n";
            }
        });
    }

    std::cout << "  GET  /ping\n  GET  /health\n";
    if (mode == ServiceMode::Embedding) std::cout << "  POST /embed\n";
    else std::cout << "  POST /v1/chat/completions (supports JSON with prompt + history, optional ?purpose=summary|query_parsing)\n";
}
