"""Synthetic evaluator fixtures are unit tests, not real-model evidence."""
import copy
import json
from pathlib import Path

from src.evaluation import action_after_search, compare_decisions, live_path_errors
from tests.helpers import AS_OF


def event(number, action, observation, executed=True, round_=None):
    return {"step": number, "round": round_ or number, "call_id": f"call-{number}", "action": action,
            "executed": executed, "ok": observation["ok"], "observation": observation,
            "parameters": {"query": "远程办公", "top_k": 5} if action == "search_docs" else {"doc_id": "D03"}}


def traces():
    # The mode value exercises evaluator branches in memory only; never serialized as Live artifacts.
    base = {"mode": "live", "requested_model": "synthetic-model", "input": {"question": "same", "history": []},
            "final": {"status": "COMPLETED"}, "steps": []}
    rejected = {"ok": False, "error_type": "QUESTION_CONTRACT_ERROR"}
    success = {"ok": True, "results": [{"doc_id": "D03"}]}
    failure = {"ok": False, "error_type": "INJECTED_FAILURE"}
    normal, changed = copy.deepcopy(base), copy.deepcopy(base)
    normal["steps"] = [event(1, "search_docs", rejected, False), event(2, "search_docs", success),
                       event(3, "read_doc", {"ok": True, "doc_id": "D03"})]
    changed["steps"] = [event(1, "search_docs", rejected, False), event(2, "search_docs", failure),
                        event(3, "search_docs", success)]
    return normal, changed


def test_dynamic_normal_regression_skips_contract_rejections():
    normal, changed = traces()
    comparison = compare_decisions(normal, changed)
    assert comparison["passed"]
    assert comparison["normal"]["observation_call_id"] == "call-2"
    assert comparison["changed"]["observation"]["error_type"] == "INJECTED_FAILURE"
    assert comparison["normal"]["action"] == "read_doc"
    assert comparison["changed"]["action"] == "search_docs"


def test_unexecuted_or_only_invalid_search_cannot_prove_dynamic_behavior():
    normal, changed = traces()
    changed["steps"][1]["executed"] = False
    assert not compare_decisions(normal, changed)["passed"]
    assert action_after_search({"steps": normal["steps"][:1]}) is None


def test_parallel_batch_does_not_prove_observation_driven_decision():
    normal, _ = traces()
    normal["steps"][2]["round"] = normal["steps"][1]["round"]
    assert action_after_search(normal) is None


def test_original_C06B_false_pass_is_rejected(corpus):
    trace = {"mode": "live", "model": "synthetic-model", "corpus_hash": corpus.hash,
             "config": {"as_of": AS_OF}, "counts": {"model_calls": 8},
             "final": {"status": "INCOMPLETE", "citations": []},
             "steps": [event(i, "search_docs", {"ok": False, "error_type": "QUESTION_CONTRACT_ERROR"}, False) for i in range(1, 9)]}
    errors = live_path_errors(trace, corpus, "search_docs:always")
    assert "未实际触发并观察注入工具故障" in errors
    assert "未完成实际业务工具执行及观察后的模型轮次" in errors


def test_failed_dynamic_business_result_cannot_pass():
    normal, changed = traces()
    normal["final"]["status"] = "INCOMPLETE"
    assert not compare_decisions(normal, changed)["passed"]
