"""Optional execution, mandatory acceptance: skips are NOT live passes."""
import json
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from src.agent import Agent
from src.evaluation import FIXED_AS_OF, mutate, compare_decisions, live_path_errors
from src.main import ROOT, live_client
from src.trace import write_json

pytestmark = pytest.mark.live
CASES = json.loads((ROOT / "examples/cases.json").read_text(encoding="utf-8"))


def live_run(corpus, question, name, history=None, fault=None):
    load_dotenv(ROOT / ".env")
    client = live_client()
    result, trace = Agent(corpus, client, fault=fault, config={"evaluation": name,
                          "evaluation_batch": os.getenv("EVIDENCE_EVALUATION_RUN_ID", "manual")}).run(
        question, history or [], FIXED_AS_OF)
    directory = ROOT / "examples/generated/live" / (name + "_" + trace["run_id"])
    result["trace_path"] = str(directory / "trace.json")
    write_json(directory / "input.json", {**trace["input"], "as_of": FIXED_AS_OF})
    write_json(directory / "corpus.json", corpus.data)
    write_json(directory / "trace.json", trace)
    write_json(directory / "output.json", result)
    path_errors = live_path_errors(trace, corpus, fault)
    write_json(directory / "path_validation.json", {"passed": not path_errors, "errors": path_errors})
    assert not path_errors, path_errors
    return result, trace, directory


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_live_six_scenarios(corpus, case):
    history = json.loads((ROOT / case["history_file"]).read_text(encoding="utf-8")) if case["history_file"] else []
    result, trace, _ = live_run(corpus, case["question"], case["id"], history, case["fault"])
    if case["id"] == "C06":
        assert result["status"] in {"COMPLETED", "FAILED"}
        assert any(not s["ok"] for s in trace["steps"])
    elif case["id"] == "C06B":
        assert result["status"] in {"FAILED", "INCOMPLETE"}
    else:
        assert result["status"] == case["expected_status"]
    if case["id"] in {"C01", "C04"}:
        assert any(c["rule_id"] == "D03-R1" and c["value"] == 2 for c in result["claims"])
    if case["id"] == "C02":
        assert {"D01", "D02"} <= {c["doc_id"] for c in result["citations"]}
    if case["id"] == "C05":
        assert {c["doc_id"] for c in result["citations"]} == {"D04"}


@pytest.mark.parametrize("variant", ["T01", "T02", "T03", "T04", "T05", "T06"])
def test_live_mutations(corpus, variant):
    changed = mutate(corpus, variant)
    question = "差旅费用最晚什么时候报销？" if variant in {"T03", "T04"} else "正式员工一周最多远程办公几天？"
    result, trace, _ = live_run(changed, question, variant, fault="search_docs:once" if variant == "T06" else None)
    if variant in {"T01", "T02"}:
        assert result["status"] == "COMPLETED"
        assert any(c["rule_id"] == "D03-R1" and c["value"] == (2 if variant == "T01" else 1) for c in result["claims"])
    elif variant == "T03":
        assert result["status"] == "NEEDS_CLARIFICATION" and result["conflicts"]
    elif variant == "T04":
        assert result["status"] == "COMPLETED" and not result["conflicts"]
    elif variant == "T05":
        assert result["status"] == "INSUFFICIENT_EVIDENCE"
        assert not {"D03", "D04"} & {c["doc_id"] for c in result["citations"]}
    else:
        assert any(s["observation"].get("error_type") == "INJECTED_FAILURE" for s in trace["steps"])
        assert result["status"] in {"COMPLETED", "FAILED"}


def test_live_observation_changes_decision(corpus):
    question = "正式员工一周最多远程办公几天？"
    normal, normal_trace, directory_a = live_run(corpus, question, "dynamic_normal")
    changed, changed_trace, directory_b = live_run(corpus, question, "dynamic_fault", fault="search_docs:once")
    comparison = compare_decisions(normal_trace, changed_trace)
    comparison.update({"normal_trace": str(directory_a / "trace.json"), "changed_trace": str(directory_b / "trace.json")})
    write_json(directory_b / "comparison.json", comparison)
    assert normal["status"] == "COMPLETED"
    assert changed["status"] in {"COMPLETED", "FAILED"}
    assert comparison["passed"], comparison["reason"]
