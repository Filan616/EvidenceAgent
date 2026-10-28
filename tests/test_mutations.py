import pytest

from src.agent import Agent
from src.coverage import Coverage
from src.evaluation import mutate, compare_decisions
from src.evidence_validator import EvidenceValidator
from src.llm_client import ScriptedClient, assistant, call
from src.rules import Corpus
from src.tools import Tools
from tests.helpers import AS_OF, args, contract, normal_script, submission
from tests.test_evidence_validator import setup


@pytest.mark.parametrize("variant,value", [("T01", 2), ("T02", 1)])
def test_remote_changes_affect_valid_output(corpus, variant, value):
    changed = mutate(corpus, variant)
    result, trace = Agent(changed, ScriptedClient(normal_script(changed))).run(
        "正式员工一周最多远程办公几天？", as_of=AS_OF)
    assert result["status"] == "COMPLETED"
    assert result["claims"][0]["value"] == value
    assert f"最多可以申请{value}天" in result["answer"]
    if variant == "T02":
        assert trace["corpus_hash"] != corpus.hash
        assert not setup(changed).validate(submission(corpus))["ok"]


def test_T03_T04_conflict_changes(corpus):
    for variant, expected in [("T03", False), ("T04", True)]:
        changed = mutate(corpus, variant)
        validator = setup(changed, "差旅报销最晚什么时候？", contract("travel_reimbursement", "all_employees", None), ("D01", "D02"))
        payload = submission(changed, ("D01-R1", "D02-R1"))
        assert validator.validate(payload)["ok"] == expected
        if variant == "T04":
            assert not validator.validate(submission(changed, ("D01-R1", "D02-R1"), "NEEDS_CLARIFICATION"))["ok"]


def test_T05_deleted_docs_not_reused(corpus):
    changed = mutate(corpus, "T05")
    tools = Tools(changed)
    assert tools.execute("read_doc", {"doc_id": "D03"})["error_type"] == "NOT_FOUND"
    coverage = Coverage("正式员工远程办公？", [], AS_OF)
    assert coverage.accept(contract(period=None)) == []
    assert not EvidenceValidator(changed, tools, coverage).validate(submission(corpus))["ok"]
    script = [assistant(call("search_docs", args(query="远程办公", top_k=5, question_contract=contract()), "d1")),
              assistant(call("submit_answer", submission(changed, (), "INSUFFICIENT_EVIDENCE"), "d2"))]
    result, trace = Agent(changed, ScriptedClient(script)).run("正式员工一周最多远程办公几天？", as_of=AS_OF)
    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert not result["citations"] and trace["steps"][0]["observation"]["results"] == []


def test_T06_actual_fault_observation_changes(corpus):
    script = normal_script(corpus)
    script.insert(1, assistant(call("search_docs", args(query="正式员工远程办公", top_k=5), "retry")))
    _, trace = Agent(corpus, ScriptedClient(script), fault="search_docs:once").run(
        "正式员工一周最多远程办公几天？", as_of=AS_OF)
    assert not trace["steps"][0]["observation"]["ok"]
    assert trace["steps"][1]["observation"]["ok"]
    assert not compare_decisions(trace, trace)["passed"]  # No fake live evidence.


def test_unsynchronized_mutation_fails(raw):
    raw["documents"][2]["rules"][0]["value"] = 1
    with pytest.raises(ValueError):
        Corpus(raw)
