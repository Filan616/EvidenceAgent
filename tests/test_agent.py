import json

import pytest

from src.agent import Agent
from src.llm_client import ScriptedClient, assistant, call
from tests.helpers import AS_OF, args, contract, normal_script, conflict_script, missing_script, submission


def run(corpus, responses, question="正式员工一周最多远程办公几天？", **kwargs):
    client = ScriptedClient(responses)
    agent = Agent(corpus, client, **kwargs)
    result, trace = agent.run(question, as_of=AS_OF)
    return result, trace, client, agent


@pytest.mark.parametrize("fixture,question,status", [
    (normal_script, "正式员工一周最多远程办公几天？", "COMPLETED"),
    (conflict_script, "差旅费用最晚什么时候报销？", "NEEDS_CLARIFICATION"),
    (missing_script, "公司今年利润是多少？", "INSUFFICIENT_EVIDENCE")])
def test_scenarios_and_protocol(corpus, fixture, question, status):
    result, trace, client, agent = run(corpus, fixture(corpus), question)
    assert result["status"] == status
    assert trace["mode"] == "mock" and trace["model"] == "mock"
    assert trace["counts"]["model_calls"] >= 2
    for request in client.messages:
        pending = set()
        for msg in request:
            if msg["role"] == "assistant" and msg.get("tool_calls"):
                assert not pending
                pending = {c["id"] for c in msg["tool_calls"]}
            elif msg["role"] == "tool":
                assert msg["tool_call_id"] in pending
                pending.remove(msg["tool_call_id"])
        assert not pending
    assert trace["steps"][-1]["next_action"] is None
    assert trace["steps"][0]["next_action"] in {"read_doc", "submit_answer"}


def test_multiple_calls_and_mixed_submit(corpus):
    script = [assistant(call("read_doc", args(doc_id="D03", question_contract=contract()), "p1"),
                        call("submit_answer", submission(corpus), "p2")),
              assistant(call("submit_answer", submission(corpus), "p3"))]
    result, trace, client, _ = run(corpus, script)
    assert result["status"] == "COMPLETED"
    assert trace["steps"][1]["observation"]["error_type"] == "MIXED_TERMINATION"
    assert {m["tool_call_id"] for m in client.messages[1] if m["role"] == "tool"} == {"p1", "p2"}


def test_over_budget_batch_fully_observed_without_executing(corpus):
    script = [assistant(call("read_doc", args(doc_id="D01", question_contract=contract("travel_reimbursement", "all_employees", None)), "b1"),
                        call("read_doc", args(doc_id="D02"), "b2"),
                        call("submit_answer", submission(corpus), "b3"))]
    result, trace, client, agent = run(corpus, script, "差旅报销最晚什么时候？", max_tool_calls=1)
    assert result["status"] == "INCOMPLETE"
    assert trace["counts"] == {"model_calls": 1, "requested": 3, "attempted": 1, "executed": 1, "skipped": 2}
    assert [s["executed"] for s in trace["steps"]] == [True, False, False]
    assert [s["observation"]["error_type"] for s in trace["steps"][1:]] == ["BUDGET_EXCEEDED"] * 2
    assert len([m for m in agent.messages if m["role"] == "tool"]) == 3
    assert len(client.messages) == 1


def test_final_valid_submit_at_budget(corpus):
    result, _, _, _ = run(corpus, normal_script(corpus), max_steps=3, max_tool_calls=3)
    assert result["status"] == "COMPLETED"


def test_failed_submit_is_repairable(corpus):
    script = normal_script(corpus)
    bad = submission(corpus)
    bad["claims"][0]["value"] = 99
    script.insert(2, assistant(call("submit_answer", bad, "bad")))
    result, trace, client, _ = run(corpus, script)
    assert result["status"] == "COMPLETED"
    assert trace["steps"][2]["observation"]["error_type"] == "VALIDATION_ERROR"
    assert "VALIDATION_ERROR" in str(client.messages[-1])


@pytest.mark.parametrize("bad_arguments", ["{", "[]", '{"doc_id":"D03","reason":"x","question_contract":null,"extra":1}'])
def test_invalid_parameters_are_observations(corpus, bad_arguments):
    bad = call("read_doc", {}, "bad")
    bad["function"]["arguments"] = bad_arguments
    result, trace, _, _ = run(corpus, [assistant(bad)], max_steps=1)
    assert result["status"] == "INCOMPLETE"
    assert trace["steps"][0]["observation"]["error_type"] == "INVALID_ARGUMENTS"


def test_plain_text_is_not_success(corpus):
    result, _, _, _ = run(corpus, [{"role": "assistant", "content": "2天"}], max_steps=1)
    assert result["status"] == "INCOMPLETE"


def test_duplicate_call_ids_fail(corpus):
    c = call("read_doc", args(doc_id="D03", question_contract=contract()), "same")
    result, _, _, _ = run(corpus, [assistant(c, c)])
    assert result["status"] == "FAILED"


def test_no_progress(corpus):
    script = [assistant(call("search_docs", args(query="正式员工远程办公", top_k=5,
              question_contract=contract() if i == 0 else None), str(i))) for i in range(3)]
    result, trace, _, _ = run(corpus, script)
    assert "NO_PROGRESS" in result["gaps"][0]
    assert trace["counts"]["attempted"] == 3


def test_error_once_observation_and_recovery(corpus):
    script = normal_script(corpus)
    script.insert(1, assistant(call("search_docs", args(query="正式员工远程办公", top_k=5), "retry")))
    result, trace, client, _ = run(corpus, script, fault="search_docs:once")
    assert result["status"] == "COMPLETED"
    assert trace["steps"][0]["observation"]["error_type"] == "INJECTED_FAILURE"
    assert "INJECTED_FAILURE" in str(client.messages[1])


def test_error_always_model_chooses_failed(corpus):
    script = normal_script(corpus)[:1] + [assistant(call("submit_answer", submission(corpus, (), "FAILED"), "failure"))]
    result, _, _, _ = run(corpus, script, fault="search_docs:always")
    assert result["status"] == "FAILED"


def test_api_error_not_faked(corpus):
    result, trace, _, _ = run(corpus, [RuntimeError("transport failed")])
    assert result["status"] == "FAILED"
    assert not trace["steps"] and not trace["rounds"][0]["ok"]


@pytest.mark.parametrize("response", [{"role": "assistant", "tool_calls": ["invalid"]},
                                    {"role": "assistant", "tool_calls": "invalid"},
                                    {"role": "assistant", "tool_calls": [{"id": "x"}]}])
def test_malformed_call_structure_fails_cleanly(corpus, response):
    result, trace, _, _ = run(corpus, [response])
    assert result["status"] == "FAILED"
    assert not trace["steps"] and not trace["rounds"][0]["ok"]
