#include "register_routes.h"
#include "run_inference.h"
#include "model_loader.h"
#include "service_config.h"
#include <iostream>
#include <sstream>
#include <vector>
#include <utility>
#include <ctime>
#include <cstdlib>
#include <cstring>
#include <algorithm>
#include <cctype>

// ═══════════════════════════════════════════════════════════════════════════════
// JSON utilities
// ═══════════════════════════════════════════════════════════════════════════════

static std::string json_escape(const std::string& s) {
    std::ostringstream out;
    for (unsigned char c : s) {
        switch (c) {
            case '"':  out << "\\\""; break;
            case '\\': out << "\\\\"; break;
            case '\n': out << "\\n";  break;
            case '\r': out << "\\r";  break;
            case '\t': out << "\\t";  break;
            case '\b': out << "\\b";  break;
            case '\f': out << "\\f";  break;
            default:
                if (c < 32) {
                    char hex[8]; snprintf(hex, sizeof(hex), "\\u%04x", c);
                    out << hex;
                } else {
                    out << c;
                }
        }
    }
    return out.str();
}

static void skip_ws(const std::string& s, size_t& i) {
    while (i < s.size() &&
           (s[i] == ' ' || s[i] == '\t' || s[i] == '\n' || s[i] == '\r'))
        ++i;
}

// Parse a JSON string literal.  Cursor must be at the opening '"'.
// Advances i past the closing '"'.
static std::string json_parse_string(const std::string& s, size_t& i) {
    if (i >= s.size() || s[i] != '"') return "";
    ++i;
    std::string result;
    result.reserve(128);
    while (i < s.size() && s[i] != '"') {
        if (s[i] == '\\') {
            ++i;
            if (i >= s.size()) break;
            switch (s[i]) {
                case '"':  result += '"';  break;
                case '\\': result += '\\'; break;
                case '/':  result += '/';  break;
                case 'n':  result += '\n'; break;
                case 'r':  result += '\r'; break;
                case 't':  result += '\t'; break;
                case 'b':  result += '\b'; break;
                case 'f':  result += '\f'; break;
                case 'u':  // \uXXXX — skip 4 hex digits (simplified)
                    for (int k = 0; k < 4 && i + 1 < s.size(); ++k) ++i;
                    break;
                default: result += s[i]; break;
            }
        } else {
            result += s[i];
        }
        ++i;
    }
    if (i < s.size()) ++i;  // consume closing '"'
    return result;
}

// Skip any complete JSON value (handles arbitrary nesting).
static void json_skip_value(const std::string& s, size_t& i) {
    skip_ws(s, i);
    if (i >= s.size()) return;
    if (s[i] == '"') { json_parse_string(s, i); return; }
    if (s[i] == '{' || s[i] == '[') {
        char open  = s[i];
        char close = (open == '{') ? '}' : ']';
        int depth = 1; ++i;
        while (i < s.size() && depth > 0) {
            if (s[i] == '"') { json_parse_string(s, i); continue; }
            if (s[i] == open)  ++depth;
            if (s[i] == close) --depth;
            ++i;
        }
        return;
    }
    // number / bool / null
    while (i < s.size() &&
           s[i] != ',' && s[i] != '}' && s[i] != ']' &&
           s[i] != ' ' && s[i] != '\n' && s[i] != '\r' && s[i] != '\t')
        ++i;
}

// ═══════════════════════════════════════════════════════════════════════════════
// OpenAI request / response helpers
// ═══════════════════════════════════════════════════════════════════════════════

struct ParsedChatRequest {
    std::string         model;
    std::vector<Message> messages;
    float               temperature = -1.0f;  // < 0 → use preset
    int                 max_tokens  = -1;     // < 1 → use preset
    bool                stream      = false;
};

// Full single-pass parser for the OpenAI chat-completion request body.
static bool parse_chat_request(const std::string& body, ParsedChatRequest& out) {
    if (body.empty() || body[0] != '{') return false;

    size_t i = 1;  // past opening '{'
    while (i < body.size()) {
        skip_ws(body, i);
        if (i >= body.size() || body[i] == '}') break;
        if (body[i] != '"') { ++i; continue; }

        std::string key = json_parse_string(body, i);
        skip_ws(body, i);
        if (i < body.size() && body[i] == ':') ++i;
        skip_ws(body, i);

        if (key == "model") {
            if (i < body.size() && body[i] == '"')
                out.model = json_parse_string(body, i);
            else
                json_skip_value(body, i);

        } else if (key == "temperature") {
            size_t start = i;
            while (i < body.size() &&
                   (std::isdigit(static_cast<unsigned char>(body[i])) ||
                    body[i] == '.' || body[i] == '-' ||
                    body[i] == 'e' || body[i] == 'E' || body[i] == '+'))
                ++i;
            if (i > start) {
                try { out.temperature = std::stof(body.substr(start, i - start)); }
                catch (...) {}
            }

        } else if (key == "max_tokens") {
            size_t start = i;
            while (i < body.size() &&
                   (std::isdigit(static_cast<unsigned char>(body[i])) ||
                    body[i] == '-'))
                ++i;
            if (i > start) {
                try { out.max_tokens = std::stoi(body.substr(start, i - start)); }
                catch (...) {}
            }

        } else if (key == "stream") {
            if (i + 4 <= body.size() && body.compare(i, 4, "true")  == 0)
                { out.stream = true;  i += 4; }
            else if (i + 5 <= body.size() && body.compare(i, 5, "false") == 0)
                { out.stream = false; i += 5; }
            else
                json_skip_value(body, i);

        } else if (key == "messages") {
            if (i >= body.size() || body[i] != '[') {
                json_skip_value(body, i);
            } else {
                ++i;  // consume '['
                while (i < body.size()) {
                    skip_ws(body, i);
                    if (i >= body.size()) break;
                    if (body[i] == ']') { ++i; break; }
                    if (body[i] != '{') { json_skip_value(body, i); goto next_msg; }

                    {
                        ++i;  // consume '{'
                        Message msg;
                        while (i < body.size()) {
                            skip_ws(body, i);
                            if (i >= body.size() || body[i] == '}') {
                                if (i < body.size()) ++i;
                                break;
                            }
                            if (body[i] != '"') { ++i; continue; }

                            std::string mkey = json_parse_string(body, i);
                            skip_ws(body, i);
                            if (i < body.size() && body[i] == ':') ++i;
                            skip_ws(body, i);

                            if (mkey == "role") {
                                if (i < body.size() && body[i] == '"')
                                    msg.role = json_parse_string(body, i);
                                else
                                    json_skip_value(body, i);
                            } else if (mkey == "content") {
                                // content can be a string or null
                                if (i < body.size() && body[i] == '"')
                                    msg.content = json_parse_string(body, i);
                                else
                                    json_skip_value(body, i);
                            } else {
                                json_skip_value(body, i);
                            }

                            skip_ws(body, i);
                            if (i < body.size() && body[i] == ',') ++i;
                        }
                        if (!msg.role.empty())
                            out.messages.push_back(std::move(msg));
                    }

                    next_msg:
                    skip_ws(body, i);
                    if (i < body.size() && body[i] == ',') ++i;
                }
            }

        } else {
            json_skip_value(body, i);
        }

        skip_ws(body, i);
        if (i < body.size() && body[i] == ',') ++i;
    }

    return !out.messages.empty();
}

static std::string make_chat_completion_json(const std::string& content,
                                              const std::string& model,
                                              int prompt_tokens,
                                              int completion_tokens) {
    auto now = static_cast<long long>(std::time(nullptr));

    char id_buf[32];
    snprintf(id_buf, sizeof(id_buf), "chatcmpl-%llx", (unsigned long long)now);

    int total = prompt_tokens + completion_tokens;

    std::ostringstream j;
    j << "{"
      << "\"id\":\""      << id_buf                   << "\","
      << "\"object\":\"chat.completion\","
      << "\"created\":"   << now                       << ","
      << "\"model\":\""   << json_escape(model)        << "\","
      << "\"choices\":[{"
      <<   "\"index\":0,"
      <<   "\"message\":{"
      <<     "\"role\":\"assistant\","
      <<     "\"content\":\"" << json_escape(content) << "\""
      <<   "},"
      <<   "\"finish_reason\":\"stop\""
      << "}],"
      << "\"usage\":{"
      <<   "\"prompt_tokens\":"     << prompt_tokens     << ","
      <<   "\"completion_tokens\":" << completion_tokens  << ","
      <<   "\"total_tokens\":"      << total
      << "}"
      << "}";
    return j.str();
}

// Map the model name from the request (or an explicit ?purpose= param) to
// the purpose key understood by run_inference / model registry.
//   • "mistral*" or explicit summarization/query_parsing/intent → Mistral (summarization)
//   • "llama*", "gpt*", or explicit chat/qa                    → Llama  (chat)
static std::string resolve_purpose(const std::string& model_name,
                                   const std::string& explicit_purpose) {
    if (!explicit_purpose.empty())
        return explicit_purpose;

    std::string lc = model_name;
    std::transform(lc.begin(), lc.end(), lc.begin(), ::tolower);
    if (lc.find("mistral")        != std::string::npos ||
        lc.find("summarization")  != std::string::npos ||
        lc.find("query_parsing")  != std::string::npos ||
        lc.find("intent")         != std::string::npos)
        return "summarization";

    return "chat";
}

// ═══════════════════════════════════════════════════════════════════════════════
// Auth helper
// ═══════════════════════════════════════════════════════════════════════════════

static bool check_auth(const httplib::Request& req, const std::string& api_key) {
    if (api_key.empty()) return true;
    std::string auth = req.get_header_value("Authorization");
    if (auth.size() > 7 && auth.compare(0, 7, "Bearer ") == 0 &&
        auth.substr(7) == api_key)
        return true;
    return req.get_header_value("X-Api-Key") == api_key;
}

// ═══════════════════════════════════════════════════════════════════════════════
// Route registration
// ═══════════════════════════════════════════════════════════════════════════════

void register_routes(httplib::Server& svr, ServiceMode mode, const std::string& api_key) {
    set_service_config(mode, api_key);

    auto auth = [api_key](const httplib::Request& req, httplib::Response& res) -> bool {
        if (!check_auth(req, api_key)) {
            res.status = 401;
            res.set_content("{\"error\":\"Missing or invalid API key\"}", "application/json");
            return false;
        }
        return true;
    };

    std::cout << "Registering routes (mode: "
              << (mode == ServiceMode::Embedding ? "embedding" : "summarization")
              << ")...\n";

    // ── Health / diagnostic endpoints ─────────────────────────────────────────

    svr.Get("/ping", [](const httplib::Request&, httplib::Response& res) {
        res.set_content("pong", "text/plain");
    });

    svr.Get("/health", [](const httplib::Request&, httplib::Response& res) {
        res.set_content("{\"status\":\"ok\",\"service\":\"inference-api\"}", "application/json");
    });

    // ── /v1/models ────────────────────────────────────────────────────────────
    // LlamaIndex's OpenAILike client may probe this on first use.
    svr.Get("/v1/models", [api_key, auth](const httplib::Request& req, httplib::Response& res) {
        if (!auth(req, res)) return;
        res.set_content(
            "{"
            "\"object\":\"list\","
            "\"data\":["
            "{\"id\":\"llama-3.1-8b\",\"object\":\"model\",\"created\":0,\"owned_by\":\"notelite\"},"
            "{\"id\":\"mistral-7b\",\"object\":\"model\",\"created\":0,\"owned_by\":\"notelite\"},"
            // Include the agent's configured model name so the client never gets a 404.
            "{\"id\":\"gpt-3.5-turbo\",\"object\":\"model\",\"created\":0,\"owned_by\":\"notelite\"}"
            "]"
            "}",
            "application/json"
        );
    });

    // ── Mode-specific endpoints ───────────────────────────────────────────────

    if (mode == ServiceMode::Embedding) {

        svr.Post("/embed", [auth](const httplib::Request& req, httplib::Response& res) {
            if (!auth(req, res)) return;
            if (req.body.empty()) {
                res.status = 400;
                res.set_content("{\"error\":\"Empty request body\"}", "application/json");
                return;
            }
            if (req.body.length() > 65536) {
                res.status = 413;
                res.set_content("{\"error\":\"Request too large (max 65536 bytes)\"}", "application/json");
                return;
            }
            try {
                std::vector<float> emb = run_embed(req.body);
                if (emb.empty()) {
                    res.status = 500;
                    res.set_content("{\"error\":\"Embedding failed\"}", "application/json");
                    return;
                }
                std::ostringstream j;
                j << "{\"embedding\":[";
                for (size_t k = 0; k < emb.size(); k++)
                    j << (k ? "," : "") << emb[k];
                j << "]}";
                res.set_content(j.str(), "application/json");
            } catch (const std::exception& e) {
                res.status = 500;
                res.set_content("{\"error\":\"" + json_escape(e.what()) + "\"}", "application/json");
            }
        });

    } else {

        // ── POST /v1/chat/completions ─────────────────────────────────────────
        // Full OpenAI-compatible chat completion endpoint.
        svr.Post("/v1/chat/completions", [auth](const httplib::Request& req, httplib::Response& res) {
            if (!auth(req, res)) return;

            if (req.body.empty()) {
                res.status = 400;
                res.set_content("{\"error\":\"Empty request body\"}", "application/json");
                std::cout << "POST /v1/chat/completions -> 400 (empty)\n";
                return;
            }
            if (req.body.length() > 131072) {  // 128 KB hard cap
                res.status = 413;
                res.set_content("{\"error\":\"Request body too large\"}", "application/json");
                std::cout << "POST /v1/chat/completions -> 413\n";
                return;
            }

            // ── Parse request ───────────────────────────────────────────────
            ParsedChatRequest cr;
            if (!parse_chat_request(req.body, cr)) {
                res.status = 400;
                res.set_content(
                    "{\"error\":\"Invalid request: expected JSON with \\\"messages\\\" array\"}",
                    "application/json"
                );
                std::cout << "POST /v1/chat/completions -> 400 (bad JSON)\n";
                return;
            }

            // ?purpose= query param overrides model-name routing.
            std::string explicit_purpose = req.get_param_value("purpose");
            std::string purpose = resolve_purpose(cr.model, explicit_purpose);

            // ── Validate ────────────────────────────────────────────────────
            if (cr.stream) {
                // Streaming not implemented; return a clear error so the client
                // falls back cleanly rather than hanging.
                res.status = 501;
                res.set_content(
                    "{\"error\":\"Streaming (stream=true) is not supported by this server\"}",
                    "application/json"
                );
                std::cout << "POST /v1/chat/completions -> 501 (streaming not supported)\n";
                return;
            }

            // ── Run inference ───────────────────────────────────────────────
            try {
                CompletionResult cr_out = run_chat_completion(
                    cr.messages,
                    purpose,
                    cr.temperature,
                    cr.max_tokens
                );

                if (!cr_out.text.empty() && cr_out.text.compare(0, 6, "Error:") == 0) {
                    res.status = 500;
                    res.set_content("{\"error\":\"" + json_escape(cr_out.text) + "\"}", "application/json");
                    std::cout << "POST /v1/chat/completions -> 500 (" << cr_out.text << ")\n";
                    return;
                }

                std::string resp_model = cr.model.empty() ? "notelite-inference" : cr.model;
                std::string json_resp  = make_chat_completion_json(
                    cr_out.text, resp_model,
                    cr_out.prompt_tokens, cr_out.completion_tokens
                );
                res.set_content(json_resp, "application/json");
                std::cout << "POST /v1/chat/completions -> 200 (purpose=" << purpose
                          << ", prompt=" << cr_out.prompt_tokens
                          << ", completion=" << cr_out.completion_tokens << ")\n";

            } catch (const std::exception& e) {
                res.status = 500;
                res.set_content(
                    "{\"error\":\"Internal error: " + json_escape(e.what()) + "\"}",
                    "application/json"
                );
                std::cout << "POST /v1/chat/completions -> 500 (exception)\n";
            } catch (...) {
                res.status = 500;
                res.set_content("{\"error\":\"Unknown internal error\"}", "application/json");
                std::cout << "POST /v1/chat/completions -> 500 (unknown)\n";
            }
        });

    }

    std::cout << "  GET  /ping\n"
              << "  GET  /health\n"
              << "  GET  /v1/models\n";
    if (mode == ServiceMode::Embedding)
        std::cout << "  POST /embed\n";
    else
        std::cout << "  POST /v1/chat/completions  "
                     "(OpenAI-compatible; ?purpose=summarization|chat)\n";
}
