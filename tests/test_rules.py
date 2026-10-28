import copy

import pytest

from src.rules import Corpus, render_rule
from tests.conftest import AS_OF


def test_overlap_and_new_date_not_precedence(corpus):
    a, b = corpus.rules["D01-R1"], corpus.rules["D02-R1"]
    assert corpus.relation(a, b, AS_OF, ["all_employees"]) == "conflict"
    assert corpus.relation(corpus.rules["D03-R1"], corpus.rules["D04-R1"], AS_OF, ["all_employees"]) == "unrelated"


def test_explicit_override(raw):
    raw["documents"][1]["rules"][0]["supersedes"] = ["D01-R1"]
    c = Corpus(raw)
    assert c.relation(c.rules["D01-R1"], c.rules["D02-R1"], AS_OF, ["regular"]) == "overridden"
    assert [r["rule_id"] for r in c.applicable("travel_reimbursement", ["regular"], AS_OF)] == ["D02-R1"]


def test_bounds_are_not_automatically_conflicts(raw):
    raw["rule_groups"]["travel_reimbursement"]["semantics"] = "bounds"
    c = Corpus(raw)
    assert c.relation(c.rules["D01-R1"], c.rules["D02-R1"], AS_OF, ["regular"]) == "consistent"


def test_time_disjoint(raw):
    raw["documents"][0]["rules"][0]["effective_to"] = "2026-06-01"
    raw["documents"][1]["rules"][0]["effective_from"] = "2026-06-01"
    c = Corpus(raw)
    assert c.relation(c.rules["D01-R1"], c.rules["D02-R1"], AS_OF, ["regular"]) == "unrelated"


@pytest.mark.parametrize("mutation", ["cycle", "dangling", "operator", "evidence", "value", "date"])
def test_bad_metadata_rejected(raw, mutation):
    rule = raw["documents"][0]["rules"][0]
    if mutation == "cycle":
        rule["supersedes"] = ["D02-R1"]
        raw["documents"][1]["rules"][0]["supersedes"] = ["D01-R1"]
    elif mutation == "dangling":
        rule["supersedes"] = ["missing"]
    elif mutation == "operator":
        rule["operator"] = "="
    elif mutation == "evidence":
        rule["evidence"] = "伪造"
    elif mutation == "value":
        rule["value"] = 99
    else:
        rule["effective_to"] = "2025-01-01"
    with pytest.raises(ValueError):
        Corpus(raw)


def test_max_is_not_exact(corpus):
    assert "最多" in render_rule(corpus.rules["D03-R1"])
    assert "必须" not in render_rule(corpus.rules["D03-R1"])


@pytest.mark.parametrize("first_kind,first_value,second_kind,second_value,expected", [
    ("MAX", 2, "MAX", 1, "consistent"),
    ("MAX", 2, "MIN", 3, "conflict"),
    ("MAX", 2, "MIN", 2, "consistent"),
    ("EXACT", 2, "MAX", 1, "conflict"),
    ("EXACT", 2, "MIN", 1, "consistent"),
    ("EXACT", 2, "EXACT", 1, "conflict"),
])
def test_constraint_intervals(raw, first_kind, first_value, second_kind, second_value, expected):
    doc = raw["documents"][2]
    other = copy.deepcopy(doc)
    other["doc_id"] = "D08"
    other["rules"][0]["rule_id"] = "D08-R1"
    raw["documents"].append(other)
    for item, kind, value in [(doc, first_kind, first_value), (other, second_kind, second_value)]:
        rule = item["rules"][0]
        rule["constraint_type"], rule["operator"], rule["value"] = kind, {"MAX": "<=", "MIN": ">=", "EXACT": "="}[kind], value
        rule["evidence"] = render_rule(rule)
        item["content"] = rule["evidence"]
    raw["rule_groups"]["remote_work"]["semantics"] = "bounds"
    c = Corpus(raw)
    assert c.relation(c.rules["D03-R1"], c.rules["D08-R1"], AS_OF, ["regular"]) == expected


def test_conditions_not_comparable_are_uncertain(raw):
    rule = raw["documents"][1]["rules"][0]
    rule["conditions"] = ["主管审批"]
    rule["evidence"] = render_rule(rule)
    raw["documents"][1]["content"] = rule["evidence"]
    c = Corpus(raw)
    assert c.relation(c.rules["D01-R1"], c.rules["D02-R1"], AS_OF, ["regular"]) == "uncertain"
