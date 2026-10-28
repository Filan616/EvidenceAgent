"""Regressions derived from the original DeepSeek Live traces, never Live evidence."""
import copy
import json
from pathlib import Path

import pytest

from src.coverage import Coverage
from tests.helpers import AS_OF, contract, submission
from tests.test_evidence_validator import setup
from src.contracts import normalize_arguments


@pytest.mark.parametrize("period", ["week", "weekly", "per week", "一周", "周"])
def test_live_week_aliases_are_semantically_equivalent(period):
    coverage = Coverage("正式员工一周最多远程办公几天？", [], AS_OF)
    assert coverage.accept(contract(period=period)) == []
    assert coverage.contract["requirements"][0]["period"] == "每周"


@pytest.mark.parametrize("scope,label,rid", [("regular", "正式员工", "D03-R1"), ("probation", "试用期员工", "D04-R1")])
def test_C04_C05_scope_is_not_an_extra_business_condition(corpus, scope, label, rid):
    c = contract(scope=scope, period="每周" if scope == "regular" else None)
    c["requirements"][0]["conditions"] = [label]
    validator = setup(corpus, f"{label}远程办公有什么规定？", c, (corpus.rule_docs[rid],))
    assert validator.validate(submission(corpus, (rid,)))["ok"]


def test_T06_cycle_is_not_a_deadline_reference_event(corpus):
    c = contract()
    c["requirements"][0]["reference_event"] = "每周"
    validator = setup(corpus, interpretation=c)
    assert validator.validate(submission(corpus))["ok"]


def test_T04_model_inferred_event_and_ambiguity_can_be_corrected(corpus):
    coverage = Coverage("差旅费用最晚什么时候报销？", [], AS_OF)
    first = contract("travel_reimbursement", "all_employees", None, ambiguous=True)
    first["requirements"][0]["reference_event"] = "差旅费用发生/出差结束"
    assert coverage.accept(first) == []
    correction = contract("travel_reimbursement", "all_employees", None)
    correction["revision_reason"] = "已读文档适用于全体员工，明确起算事件为差旅结束后"
    assert coverage.accept(correction) == []


def test_model_added_condition_can_be_removed_but_user_condition_cannot():
    for explicit in (False, True):
        question = "正式员工每周远程办公，主管审批条件下最多几天？" if explicit else "正式员工每周远程办公最多几天？"
        coverage = Coverage(question, [], AS_OF)
        first = contract()
        first["requirements"][0]["conditions"] = ["主管审批"]
        assert coverage.accept(first) == []
        correction = contract()
        correction["revision_reason"] = "修正模型推断"
        problems = coverage.accept(correction)
        assert bool(problems) == explicit


def test_field_provenance_separates_user_conditions_from_model_additions():
    coverage = Coverage("正式员工每周远程办公，主管审批条件下最多几天？", [], AS_OF)
    c = contract()
    c["requirements"][0]["conditions"] = ["主管审批", "需要额外证明"]
    assert coverage.accept(c) == []
    conditions = [p for p in coverage.provenance if ".conditions." in p["field"]]
    assert next(p for p in conditions if p["value"] == "主管审批")["protected"]
    assert not next(p for p in conditions if p["value"] == "需要额外证明")["protected"]
    fixed = copy.deepcopy(c)
    fixed["requirements"][0]["conditions"] = ["主管审批"]
    fixed["revision_reason"] = "删除模型添加的无依据条件"
    assert coverage.accept(fixed) == []


@pytest.mark.parametrize("field,value", [("scope", ["probation"]), ("period", "每月"), ("constraint_type", "MIN")])
def test_user_constraints_cannot_be_erased_by_revision(field, value):
    coverage = Coverage("正式员工每周最多远程办公几天？", [], AS_OF)
    assert coverage.accept(contract()) == []
    fixed = contract()
    fixed["requirements"][0][field] = value
    fixed["revision_reason"] = "试图改变用户约束"
    assert coverage.accept(fixed)
    assert coverage.field_errors
    assert all({"error_type", "field", "actual", "expected_semantics", "allowed_corrections"} <= e.keys() for e in coverage.field_errors)


def test_model_inferred_scope_can_be_corrected_when_user_did_not_specify():
    coverage = Coverage("远程办公有哪些规定？", [], AS_OF)
    first = contract(scope="probation", period=None, ambiguous=True)
    assert coverage.accept(first) == []
    corrected = contract(scope="all_employees", period=None)
    corrected["revision_reason"] = "原问题问全部规定，不应仅限制试用期"
    assert coverage.accept(corrected) == []


def test_conflicting_period_event_or_scope_is_not_silently_dropped():
    for req in [dict(period="每月", reference_event="每周"),
                dict(scope=["regular"], conditions=["试用期员工"])]:
        c = contract()
        c["requirements"][0].update(req)
        _, _, errors = normalize_arguments({"question_contract": c})
        assert errors
        assert "CONFLICT" in errors[0]["error_type"]


def test_equivalent_revision_does_not_need_a_new_explanation():
    coverage = Coverage("正式员工每周最多远程办公几天？", [], AS_OF)
    c = contract(period="weekly")
    c["revision_reason"] = "首次解释"
    assert coverage.accept(c) == []
    assert coverage.accept(contract()) == []


def test_claim_feedback_does_not_allow_false_value_or_fabricated_quote(corpus):
    validator = setup(corpus)
    payload = submission(corpus)
    payload["claims"][0]["value"] = 99
    result = validator.validate(payload)
    assert not result["ok"]
    assert any(e["field"] == "claims.0.value" and e["expected_semantics"] == 2 for e in result["field_errors"])
    payload["claims"][0]["value"] = 2
    payload["claims"][0]["evidence_quote"] = "不存在的引文"
    assert not validator.validate(payload)["ok"]


RECORDED = json.loads((Path(__file__).parent / "fixtures/live_contract_regressions.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("record", RECORDED, ids=lambda r: r["case"])
def test_actual_live_payload_regressions_through_executor(corpus, record):
    from src.agent import Agent
    from src.evaluation import mutate
    from src.llm_client import ScriptedClient, assistant, call
    from tests.helpers import args
    case = record["case"]
    changed = mutate(corpus, "T04") if case == "T04" else corpus
    script = [assistant(call("search_docs", record["first_arguments"], "recorded-first"))]
    fault = "search_docs:once" if case == "T06" else ("search_docs:always" if case == "C06B" else None)
    if fault:
        script.append(assistant(call("search_docs", args(query="正式员工远程办公", top_k=5), "retry")))
    if case == "C06B":
        script.append(assistant(call("submit_answer", submission(changed, (), "FAILED"), "finish")))
        expected = "FAILED"
    else:
        ids = ["D01", "D02"] if case == "T04" else (["D04"] if case == "C05" else ["D03"])
        for did in ids:
            script.append(assistant(call("read_doc", args(doc_id=did), "read-" + did)))
        final = submission(changed, tuple(did + "-R1" for did in ids))
        if case == "T04":
            fixed = contract("travel_reimbursement", "all_employees", None)
            fixed["revision_reason"] = "已读取全体员工规则且期限一致，修正模型推断的起算事件及歧义"
            final["question_contract"] = fixed
        script.append(assistant(call("submit_answer", final, "finish")))
        expected = "COMPLETED"
    result, trace = Agent(changed, ScriptedClient(script), fault=fault).run(record["question"], record["history"], AS_OF)
    assert result["status"] == expected
    assert trace["mode"] == "mock"  # Explicit scripted replay is NOT a new Live result.
    assert trace["config"]["max_steps"] == 8
    if fault:
        assert trace["steps"][0]["observation"]["error_type"] == "INJECTED_FAILURE"
    if case == "T04":
        assert not result["conflicts"]
