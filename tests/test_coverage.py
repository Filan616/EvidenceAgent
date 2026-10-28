from src.coverage import Coverage
from tests.helpers import AS_OF, contract, submission
from tests.test_evidence_validator import setup


def test_correct_topic_wrong_facet(corpus):
    validator = setup(corpus, "正式员工远程办公如何审批？", contract(period=None))
    result = validator.validate(submission(corpus))
    assert not result["ok"]
    assert any("流程" in e for e in result["details"])


def test_multiple_facets_not_covered_by_one_limit(corpus):
    validator = setup(corpus, "正式员工每周远程办公最多几天，怎么审批？")
    assert not validator.validate(submission(corpus))["ok"]


def test_explicit_date_mismatch_can_request_clarification():
    coverage = Coverage("2025-01-01正式员工远程办公？", [], AS_OF)
    assert coverage.accept(contract(ambiguous=True)) == []


def test_scope_and_required_condition_must_be_covered(corpus):
    c = contract()
    c["requirements"][0]["conditions"] = ["主管审批"]
    validator = setup(corpus, interpretation=c)
    assert not validator.validate(submission(corpus))["ok"]


def test_minimum_cannot_be_answered_by_maximum(corpus):
    c = contract()
    c["requirements"][0]["constraint_type"] = "MIN"
    validator = setup(corpus, "正式员工每周至少能申请几天远程办公？", c)
    assert not validator.validate(submission(corpus))["ok"]


def test_reference_event_is_explicit_constraint():
    coverage = Coverage("差旅结束前最晚什么时候报销？", [], AS_OF)
    assert coverage.accept(contract("travel_reimbursement", "all_employees", None))


def test_contract_cannot_expand_explicit_probation_scope():
    coverage = Coverage("试用期远程办公有什么规定？", [], AS_OF)
    assert coverage.accept(contract("remote_work", "all_employees", None))


def test_multiple_topics_keep_their_own_facets(corpus):
    c = contract()
    c["requirements"] += contract("annual_leave", "regular", None)["requirements"]
    question = "正式员工每周远程办公最多几天，以及正式员工年假如何申请？"
    validator = setup(corpus, question, c, ("D03", "D05"))
    assert not validator.validate(submission(corpus))["ok"]
    assert validator.validate(submission(corpus, ("D03-R1", "D05-R1")))["ok"]


def test_unspecified_scope_cannot_silently_become_regular():
    coverage = Coverage("一周在家上班最多能申请几天？", [], AS_OF)
    assert coverage.accept(contract())
    assert coverage.accept(contract(ambiguous=True)) == []


def test_unknown_employee_category_requires_clarification():
    coverage = Coverage("实习生远程办公有什么规定？", [], AS_OF)
    assert coverage.accept(contract())
    assert coverage.accept(contract(ambiguous=True)) == []
