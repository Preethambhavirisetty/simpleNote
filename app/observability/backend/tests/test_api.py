"""Integration tests against a real MySQL."""

from sqlalchemy import text

from app.core.db import get_engine

BATCH = [
    {
        "seq": 1,
        "level": "INFO",
        "phase": "resolve_playbook",
        "message": "selected playbook",
        "source": "planner.py:42",
        "track": {"playbook": "incident_triage", "score": 0.91},
    },
    {
        "seq": 2,
        "level": "DEBUG",
        "phase": "llm",
        "message": "call complete",
        "duration_ms": 842,
        "data": {"stop_reason": "tool_use"},
        "track": {"model": "sample-model", "llm_latency_ms": 842, "input_tokens": 4210},
    },
    {
        "seq": 3,
        "level": "ERROR",
        "phase": "tool",
        "message": "k8s timeout",
        "track": {"conversation_state": {"turn": 2, "slots": {"svc": "checkout-api"}}},
    },
]


# --- ingest -----------------------------------------------------------------

def test_run_counters_are_derived_from_the_logs(client, make_run):
    key = make_run(logs=BATCH)
    run = client.get(f"/api/v1/runs/{key}").json()
    assert run["log_count"] == 3
    assert run["error_count"] == 1
    assert run["max_seq"] == 3


def test_replaying_a_batch_changes_nothing(client, make_run):
    key = make_run(logs=BATCH)
    again = client.post(f"/api/v1/runs/{key}/logs", json={"logs": BATCH}).json()

    assert again["duplicates"] == 3
    run = client.get(f"/api/v1/runs/{key}").json()
    assert run["log_count"] == 3, "replay must not duplicate log rows"
    latency = next(f for f in run["fields"] if f["name"] == "llm_latency_ms")
    assert latency["count"] == 1, "replay must not duplicate tracked values"


def test_writes_are_committed_before_the_response_returns(client):
    """Regression: a `yield` dependency's cleanup runs *after* the response is
    sent, so committing there let a client see its own 200 and then issue a
    follow-up request that could not find the row it had just created."""
    client.post("/api/v1/runs", json={"run_key": "commit-check"}).raise_for_status()

    # a connection the request never touched must already see the row
    with get_engine().connect() as fresh:
        found = fresh.execute(
            text("SELECT run_key FROM runs WHERE run_key = 'commit-check'")
        ).first()
    assert found is not None, "POST /runs returned before its INSERT committed"

    # and the dependent write therefore succeeds
    res = client.post(
        "/api/v1/runs/commit-check/logs",
        json={"logs": [{"seq": 1, "message": "immediately after create"}]},
    )
    assert res.status_code == 200


def test_a_failed_write_leaves_nothing_behind(client, make_run):
    key = make_run()
    client.post(
        f"/api/v1/runs/{key}/logs",
        json={"logs": [{"seq": 1, "message": "a"}, {"seq": 1, "message": "b"}]},
    )
    # the 422 must roll back, not leave a half-written batch
    assert client.get(f"/api/v1/runs/{key}/logs").json()["items"] == []


def test_starting_the_same_run_twice_is_idempotent(client, make_run):
    make_run(run_key="dup")
    make_run(run_key="dup")
    assert client.get("/api/v1/runs").json()["items"].__len__() == 1


def test_duplicate_seq_within_one_batch_is_rejected(client, make_run):
    key = make_run()
    res = client.post(
        f"/api/v1/runs/{key}/logs",
        json={"logs": [{"seq": 1, "message": "a"}, {"seq": 1, "message": "b"}]},
    )
    assert res.status_code == 422


def test_logs_for_unknown_run_are_404(client):
    res = client.post("/api/v1/runs/nope/logs", json={"logs": BATCH})
    assert res.status_code == 404


def test_out_of_order_delivery_is_ordered_by_seq_not_arrival(client, make_run):
    key = make_run(logs=list(reversed(BATCH)))
    lines = client.get(f"/api/v1/runs/{key}/logs").json()["items"]
    assert [line["seq"] for line in lines] == [1, 2, 3]


def test_finish_sets_status_and_duration(client, make_run):
    key = make_run(logs=BATCH, started_at="2026-07-28T10:00:00")
    client.post(
        f"/api/v1/runs/{key}/finish",
        json={"status": "ok", "final_answer": "OOMKilled", "ended_at": "2026-07-28T10:00:04"},
    )
    run = client.get(f"/api/v1/runs/{key}").json()
    assert run["status"] == "ok"
    assert run["final_answer"] == "OOMKilled"
    assert run["duration_ms"] == 4000


# --- tracked fields ---------------------------------------------------------

def test_a_brand_new_field_name_needs_no_migration(client, make_run):
    """The acceptance test for the whole design."""
    key = make_run(
        logs=[{"seq": 1, "message": "novel", "track": {"retrieval_hit_rate": 0.82}}]
    )

    registry = {f["name"] for f in client.get("/api/v1/fields").json()["items"]}
    assert "retrieval_hit_rate" in registry

    run = client.get(f"/api/v1/runs/{key}").json()
    field = next(f for f in run["fields"] if f["name"] == "retrieval_hit_rate")
    assert field["value"] == 0.82
    assert field["kind"] == "number"
    assert field["aggregate"] == "avg", "'_rate' should be averaged, not summed"

    # and it is immediately filterable
    hits = client.get("/api/v1/runs?f.retrieval_hit_rate.gt=0.5").json()["items"]
    assert [r["run_key"] for r in hits] == [key]


def test_json_values_round_trip_intact(client, make_run):
    key = make_run(logs=BATCH)
    run = client.get(f"/api/v1/runs/{key}").json()
    state = next(f for f in run["fields"] if f["name"] == "conversation_state")
    assert state["value"] == {"turn": 2, "slots": {"svc": "checkout-api"}}


def test_repeated_values_collapse_by_declared_aggregate(client, make_run):
    key = make_run(
        logs=[
            {"seq": 1, "message": "a", "track": {"llm_latency_ms": 100, "score": 0.2}},
            {"seq": 2, "message": "b", "track": {"llm_latency_ms": 300, "score": 0.4}},
        ]
    )
    fields = {f["name"]: f for f in client.get(f"/api/v1/runs/{key}").json()["fields"]}
    assert fields["llm_latency_ms"]["value"] == 400, "latency sums"
    assert fields["score"]["value"] == 0.3, "score averages"
    assert fields["llm_latency_ms"]["count"] == 2


def test_tracked_values_link_back_to_their_log_line(client, make_run):
    key = make_run(logs=BATCH)
    run = client.get(f"/api/v1/runs/{key}").json()
    playbook = next(f for f in run["fields"] if f["name"] == "playbook")
    log_id = playbook["values"][0]["log_id"]

    lines = client.get(f"/api/v1/runs/{key}/logs").json()["items"]
    line = next(line for line in lines if line["id"] == log_id)
    assert line["seq"] == 1


def test_pinning_a_field_surfaces_it_on_the_runs_list(client, make_run):
    key = make_run(logs=BATCH)
    assert client.get("/api/v1/runs").json()["items"][0].get("fields") == {}

    client.patch("/api/v1/fields/playbook", json={"pinned": True})
    row = client.get("/api/v1/runs").json()["items"][0]
    assert row["fields"]["playbook"] == "incident_triage"
    assert row["run_key"] == key


# --- filtering & reads ------------------------------------------------------

def test_field_filters_select_and_exclude(client, make_run):
    make_run(run_key="a", logs=BATCH)
    make_run(
        run_key="b",
        logs=[{"seq": 1, "message": "x", "track": {"playbook": "deploy_rollback"}}],
    )

    def keys(qs):
        return {r["run_key"] for r in client.get(f"/api/v1/runs{qs}").json()["items"]}

    assert keys("?f.playbook=incident_triage") == {"a"}
    assert keys("?f.playbook.ne=incident_triage") == {"b"}
    assert keys("?f.llm_latency_ms.gt=800") == {"a"}
    assert keys("?f.llm_latency_ms.gt=9000") == set()
    assert keys("?f.model.contains=opus") == {"a"}
    assert keys("?f.playbook.in=incident_triage,deploy_rollback") == {"a", "b"}
    # multiple filters intersect
    assert keys("?f.playbook=incident_triage&f.score.gte=0.9") == {"a"}
    assert keys("?f.playbook=incident_triage&f.score.gte=0.99") == set()


def test_invalid_filter_returns_400_not_500(client):
    assert client.get("/api/v1/runs?f.playbook.gt=abc").status_code == 400


def test_log_level_filter_is_a_minimum_not_an_exact_match(client, make_run):
    key = make_run(logs=BATCH)
    warn_and_up = client.get(f"/api/v1/runs/{key}/logs?level=WARN").json()["items"]
    assert [line["level"] for line in warn_and_up] == ["ERROR"]

    everything = client.get(f"/api/v1/runs/{key}/logs?level=DEBUG").json()["items"]
    assert len(everything) == 3

    exact = client.get(f"/api/v1/runs/{key}/logs?levels=INFO,ERROR").json()["items"]
    assert {line["level"] for line in exact} == {"INFO", "ERROR"}


def test_after_seq_supports_live_tail(client, make_run):
    key = make_run(logs=BATCH)
    tail = client.get(f"/api/v1/runs/{key}/logs?after_seq=2").json()
    assert [line["seq"] for line in tail["items"]] == [3]
    assert tail["last_seq"] == 3


def test_phase_rollup(client, make_run):
    key = make_run(logs=BATCH)
    phases = {p["phase"]: p for p in client.get(f"/api/v1/runs/{key}/phases").json()["items"]}
    assert phases["tool"]["error_count"] == 1
    assert phases["llm"]["duration_ms"] == 842


def test_stats_group_by_joins_two_tracked_fields(client, make_run):
    make_run(run_key="a", logs=BATCH)
    make_run(
        run_key="b",
        logs=[
            {
                "seq": 1,
                "message": "x",
                "track": {"playbook": "deploy_rollback", "llm_latency_ms": 200},
            }
        ],
    )
    stats = client.get(
        "/api/v1/stats/fields/llm_latency_ms?group_by=playbook&agg=avg"
    ).json()
    by_playbook = {i["bucket"]: i["value"] for i in stats["items"]}
    assert by_playbook == {"incident_triage": 842, "deploy_rollback": 200}


def test_overview_counts_statuses(client, make_run):
    make_run(run_key="a", logs=BATCH)
    client.post("/api/v1/runs/a/finish", json={"status": "ok"})
    make_run(run_key="b")
    client.post("/api/v1/runs/b/finish", json={"status": "error"})

    stats = client.get("/api/v1/stats/overview").json()
    assert (stats["runs"], stats["ok"], stats["failed"]) == (2, 1, 1)


def test_pagination_is_stable_across_pages(client, make_run):
    for i in range(5):
        make_run(run_key=f"r{i}", started_at=f"2026-07-2{i}T10:00:00")

    first = client.get("/api/v1/runs?limit=2").json()
    assert len(first["items"]) == 2 and first["has_more"]

    second = client.get(f"/api/v1/runs?limit=2&cursor={first['next_cursor']}").json()
    overlap = {r["run_key"] for r in first["items"]} & {
        r["run_key"] for r in second["items"]
    }
    assert overlap == set(), "pages must not repeat rows"


def test_deleting_a_run_removes_its_logs_and_fields(client, make_run):
    key = make_run(logs=BATCH)
    assert client.delete(f"/api/v1/runs/{key}").status_code == 200
    assert client.get(f"/api/v1/runs/{key}").status_code == 404
    # the cascade is what keeps orphans out
    assert client.get("/api/v1/stats/fields/llm_latency_ms").json()["items"][0]["n"] == 0


def test_conversation_groups_runs_in_order(client, make_run):
    make_run(run_key="a", conversation_id="c1", started_at="2026-07-28T10:00:00")
    make_run(run_key="b", conversation_id="c1", started_at="2026-07-28T11:00:00")
    make_run(run_key="c", conversation_id="c2")

    runs = client.get("/api/v1/conversations/c1/runs").json()["items"]
    assert [r["run_key"] for r in runs] == ["a", "b"]
