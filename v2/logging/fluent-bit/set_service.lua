-- Map container names (from the log file path in the Tag) to a
-- human-readable service label for Loki/Grafana.

local name_map = {
    ["notelite-backend"]        = "backend",
    ["notelite-backend-celery"] = "backend",
    ["notelite-agent"]          = "agent",
    ["notelite-agent-celery"]   = "agent",
    ["nl-qdrant"]               = "qdrant",
    ["mypostgres"]              = "postgres",
    ["myredis"]                 = "redis",
    ["loki"]                    = "loki",
    ["grafana"]                 = "grafana",
    ["fluent-bit"]              = "fluent-bit",
}

function set_service(tag, timestamp, record)
    -- Tag looks like "container./var/log/containers/<name>/<name>.log"
    -- Extract the container name from between the last two slashes or
    -- by scanning for known names.
    local service = "other"
    for name, label in pairs(name_map) do
        if tag:find(name, 1, true) then
            service = label
            break
        end
    end
    record["service"] = service
    return 1, timestamp, record
end
