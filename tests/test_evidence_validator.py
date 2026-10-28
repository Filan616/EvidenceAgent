import copy

import pytest

from src.coverage import Coverage
from src.evidence_validator import EvidenceValidator
from src.rules import Corpus, render_rule
from src.tools import Tools
from tests.helpers import AS_OF, contract, submission


def setup(corpus, question="正式员工一周最多远程办公几天？", interpretation=None, reads=("D03",), history=None):
    tools = Tools(corpus)
    coverage = Coverage(question, history or [], AS_OF)
    assert coverage.accept(interpretation or contract()) == []
    for did in reads:
        tools.execute("read_doc", {"doc_id": did})
    return EvidenceValidator(corpus, tools, coverage)


def test_valid_and_ignore_untrusted_answer(corpus):
    payload = submission(corpus)
    payload["answer"] = "正式员工2天，试用期员工1天。"
    result = setup(corpus).validate(payload)
    assert result["ok"]
    assert result["result"]["answer"] == corpus.rules["D03-R1"]["evidence"]
    assert "试用期" not in result["result"]["answer"]


@pytest.mark.parametrize("mutation", ["unread", "id", "quote", "statement", "value", "unit", "operator", "period", "conditions"])
def test_invalid_claim(corpus, mutation):
    validator = setup(corpus, reads=() if mutation == "unread" else ("D03",))
    payload = submission(corpus)
    claim = payload["claims"][0]
    if mutation == "id":
        claim["evidence_doc_id"] = "nope"
    elif mutation == "quote":
        claim["evidence_quote"] = "远程办公100天"
    elif mutation == "statement":
        claim["statement"] += "试用期员工每周1天。"
    elif mutation != "unread":
        claim[mutation] = {"value": 7, "unit": "times", "operator": "=", "period": "每月", "conditions": ["无条件"]}[mutation]
    assert not validator.validate(payload)["ok"]


def test_whitespace_normalization(corpus):
    payload = submission(corpus)
    payload["claims"][0]["evidence_quote"] = "\n" + payload["claims"][0]["evidence_quote"] + "  "
    payload["citations"][0]["quote"] = payload["claims"][0]["evidence_quote"]
    assert setup(corpus).validate(payload)["ok"]


def test_unread_conflict_guard_no_unread_values(corpus):
    validator = setup(corpus, "差旅报销最晚什么时候？", contract("travel_reimbursement", "all_employees", None), ("D01",))
    result = validator.validate(submission(corpus, ("D01-R1",)))
    assert not result["ok"] and result["related_doc_ids"] == ["D01", "D02"]
    assert "15" not in str(result)


def test_conflict_requires_both_claims(corpus):
    validator = setup(corpus, "差旅报销最晚什么时候？", contract("travel_reimbursement", "all_employees", None), ("D01", "D02"))
    assert not validator.validate(submission(corpus, ("D01-R1",), "NEEDS_CLARIFICATION"))["ok"]
    assert validator.validate(submission(corpus, ("D01-R1", "D02-R1"), "NEEDS_CLARIFICATION"))["ok"]


def test_probation_not_regular(corpus):
    validator = setup(corpus, "那试用期呢？", contract("remote_work", "probation", None), ("D03", "D04"),
                      [{"role": "user", "content": "正式员工远程办公规定？"}])
    assert not validator.validate(submission(corpus))["ok"]
    result = validator.validate(submission(corpus, ("D04-R1",)))
    assert result["ok"] and "主管审批" in result["result"]["answer"]


def test_multiple_scope_subquestions(corpus):
    interpretation = contract(period=None)
    interpretation["requirements"][0]["scope"] = ["regular", "probation"]
    validator = setup(corpus, "正式员工和试用期员工远程办公分别有什么规定？", interpretation, ("D03", "D04"))
    assert not validator.validate(submission(corpus))["ok"]
    assert validator.validate(submission(corpus, ("D03-R1", "D04-R1")))["ok"]


def test_wrong_topic_and_contract_revision(corpus):
    coverage = Coverage("试用期远程办公？", [], AS_OF)
    assert coverage.accept(contract("annual_leave", "regular", None))
    assert coverage.accept(contract("remote_work", "probation", None)) == []
    revised = contract("remote_work", "regular", None)
    revised["revision_reason"] = "只找到正式员工证据"
    assert coverage.accept(revised)


def test_unknown_question_cannot_become_remote_answer(corpus):
    coverage = Coverage("公司利润多少？", [], AS_OF)
    assert coverage.accept(contract())


def test_as_of_and_period_constraints():
    coverage = Coverage("2026-01-01正式员工每周远程办公？", [], AS_OF)
    assert coverage.accept(contract())
    coverage = Coverage("正式员工每周远程办公？", [], AS_OF)
    assert coverage.accept(contract(period="每月"))


def test_expired_and_overridden_claims(raw):
    raw["documents"][0]["rules"][0]["effective_to"] = "2026-02-01"
    c = Corpus(raw)
    validator = setup(c, "差旅报销最晚什么时候？", contract("travel_reimbursement", "all_employees", None), ("D01", "D02"))
    assert not validator.validate(submission(c, ("D01-R1",)))["ok"]
    assert validator.validate(submission(c, ("D02-R1",)))["ok"]


def test_ambiguous_cannot_complete(corpus):
    interpretation = contract(ambiguous=True)
    validator = setup(corpus, interpretation=interpretation)
    assert not validator.validate(submission(corpus))["ok"]
    assert validator.validate(submission(corpus, (), "NEEDS_CLARIFICATION"))["ok"]


def test_partial_supersession_cannot_render_old_scope_as_all(raw):
    doc = raw["documents"][1]
    doc["scope"] = ["regular"]
    rule = doc["rules"][0]
    rule["scope"] = ["regular"]
    rule["supersedes"] = ["D01-R1"]
    rule["evidence"] = render_rule(rule)
    doc["content"] = rule["evidence"]
    c = Corpus(raw)
    validator = setup(c, "差旅报销最晚什么时候？", contract("travel_reimbursement", "all_employees", None), ("D01", "D02"))
    payload = submission(c, ("D01-R1", "D02-R1"))
    assert not validator.validate(payload)["ok"]
    payload["claims"][0]["scope"] = ["probation"]
    payload["claims"][0]["statement"] = render_rule({**c.rules["D01-R1"], "scope": ["probation"]})
    result = validator.validate(payload)
    assert result["ok"]
    assert "试用期员工应在差旅结束后30天" in result["result"]["answer"]
    assert "正式员工应在差旅结束后15天" in result["result"]["answer"]
