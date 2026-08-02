from decimal import Decimal

import pytest

from app.services.field_router import infer_aggregate, infer_unit, route_value


@pytest.mark.parametrize(
    "value, column, expected",
    [
        ("incident_triage", "value_text", "incident_triage"),
        (842, "value_num", Decimal("842")),
        (0.91, "value_num", Decimal("0.91")),
        (Decimal("1.5"), "value_num", Decimal("1.5")),
        ({"turn": 2}, "value_json", {"turn": 2}),
        ([1, 2, 3], "value_json", [1, 2, 3]),
    ],
)
def test_value_lands_in_the_right_column(value, column, expected):
    routed = route_value("x", value)
    assert routed[column] == expected
    others = {"value_text", "value_num", "value_json"} - {column}
    assert all(routed[o] is None for o in others)


def test_bool_is_numeric_and_not_mistaken_for_int():
    # bool subclasses int in Python, so ordering of the isinstance checks matters
    assert route_value("ok", True)["kind"] == "bool"
    assert route_value("ok", True)["value_num"] == Decimal(1)
    assert route_value("ok", False)["value_num"] == Decimal(0)
    assert route_value("n", 1)["kind"] == "number"


def test_numeric_string_becomes_aggregatable():
    routed = route_value("tokens", "4210")
    assert routed["kind"] == "number"
    assert routed["value_num"] == Decimal("4210")


def test_explicit_unit_wrapper_overrides_inference():
    assert route_value("elapsed", {"v": 12, "unit": "s"})["unit"] == "s"
    assert route_value("elapsed", {"v": 12, "unit": "s"})["value_num"] == Decimal(12)
    # a dict that is not the wrapper shape stays JSON
    assert route_value("state", {"v": 1, "other": 2})["kind"] == "json"


def test_long_text_is_truncated_to_the_column_width():
    assert len(route_value("blob", "x" * 900)["value_text"]) == 512


@pytest.mark.parametrize(
    "name, unit",
    [
        ("llm_latency_ms", "ms"),
        ("input_tokens", "tok"),
        ("cost_usd", "usd"),
        ("payload_bytes", "B"),
        ("hit_pct", "%"),
        ("playbook", None),
    ],
)
def test_unit_inference(name, unit):
    assert infer_unit(name) == unit


@pytest.mark.parametrize(
    "name, kind, aggregate",
    [
        ("llm_latency_ms", "number", "sum"),
        ("input_tokens", "number", "sum"),
        ("tool_calls", "number", "sum"),
        ("retries", "number", "sum"),
        ("score", "number", "avg"),
        ("confidence", "number", "avg"),
        ("hit_rate", "number", "avg"),
        ("playbook", "text", "last"),
        ("memory", "json", "last"),
    ],
)
def test_aggregate_inference(name, kind, aggregate):
    assert infer_aggregate(name, kind) == aggregate
