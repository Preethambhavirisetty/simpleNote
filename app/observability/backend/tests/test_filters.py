import pytest
from starlette.datastructures import QueryParams

from app.services.filters import (
    FilterError,
    build_exists_clauses,
    parse_field_filters,
)


def parse(qs: str):
    return parse_field_filters(QueryParams(qs))


def test_bare_field_defaults_to_equality():
    assert parse("f.playbook=incident_triage") == [
        ("playbook", "eq", "incident_triage")
    ]


def test_explicit_operator_is_parsed():
    assert parse("f.llm_latency_ms.gt=800") == [("llm_latency_ms", "gt", "800")]


def test_non_filter_params_are_ignored():
    assert parse("status=ok&limit=50&q=checkout") == []


def test_field_name_containing_a_dot_that_is_not_an_operator():
    # 'p95' is not an operator, so the whole thing is the field name
    assert parse("f.latency.p95=1") == [("latency.p95", "eq", "1")]


def test_multiple_filters_are_all_returned():
    got = parse("f.playbook=a&f.score.lt=0.5&f.tokens.gte=100")
    assert len(got) == 3


def test_rejects_injection_shaped_field_names():
    with pytest.raises(FilterError):
        parse("f.a b; DROP TABLE runs--=1")


def test_rejects_too_many_filters():
    with pytest.raises(FilterError):
        parse("&".join(f"f.field{i}=1" for i in range(20)))


def test_numeric_operator_uses_the_numeric_column():
    clauses, params = build_exists_clauses([("latency_ms", "gt", "800")])
    assert "value_num >" in clauses[0]
    assert "value_text" not in clauses[0]
    assert params["tf_val_0"] == pytest.approx(800)


def test_equality_on_text_uses_the_text_column():
    clauses, params = build_exists_clauses([("playbook", "eq", "triage")])
    assert "value_text =" in clauses[0]
    assert params["tf_val_0"] == "triage"


def test_equality_on_a_number_uses_the_numeric_column():
    clauses, _ = build_exists_clauses([("score", "eq", "0.9")])
    assert "value_num =" in clauses[0]


def test_comparison_against_non_numeric_value_is_rejected():
    with pytest.raises(FilterError):
        build_exists_clauses([("playbook", "gt", "abc")])


def test_contains_becomes_a_like():
    clauses, params = build_exists_clauses([("model", "contains", "opus")])
    assert "LIKE" in clauses[0]
    assert params["tf_val_0"] == "%opus%"


def test_in_expands_to_placeholders():
    clauses, params = build_exists_clauses([("playbook", "in", "a,b,c")])
    assert clauses[0].count(":tf_val_0_") == 3
    assert {params["tf_val_0_0"], params["tf_val_0_1"], params["tf_val_0_2"]} == {
        "a", "b", "c"
    }


def test_empty_in_list_is_rejected():
    with pytest.raises(FilterError):
        build_exists_clauses([("playbook", "in", " , ")])


def test_exists_false_becomes_not_exists():
    clauses, _ = build_exists_clauses([("playbook", "exists", "0")])
    assert clauses[0].startswith("NOT EXISTS")


def test_each_filter_gets_its_own_alias_so_they_can_be_combined():
    clauses, _ = build_exists_clauses(
        [("playbook", "eq", "a"), ("score", "gt", "0.5")]
    )
    assert "tf0." in clauses[0] and "tf1." in clauses[1]
    assert len(set(clauses)) == 2
