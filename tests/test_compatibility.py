import json
from types import SimpleNamespace

import httpx
import pytest
from openai import OpenAI

from src.agent import Agent
from src.llm_client import LiveClient
from src.schemas import tool_schemas
from tests.helpers import AS_OF


def transport_client(handler, **kwargs):
    sdk = OpenAI(api_key="synthetic-test-not-a-real-key", base_url="https://synthetic.invalid/v1",
                 max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    return LiveClient("synthetic-test-not-a-real-key", "synthetic-model", transport=sdk, **kwargs)


def test_real_sdk_payload_and_explicit_compatibility(corpus):
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "x", "object": "chat.completion", "created": 0,
            "model": "synthetic-model-returned", "choices": [{"index": 0, "finish_reason": "stop",
            "message": {"role": "assistant", "content": "plain text"}}]})
    for strict, parallel in [(True, True), (False, False)]:
        client = transport_client(handler, strict=strict, disable_parallel=parallel)
        reply = client.complete([{"role": "user", "content": "test"}], tool_schemas(corpus.groups, strict))
        assert reply.model == "synthetic-model-returned"
        assert ("parallel_tool_calls" in requests[-1]) == parallel
        assert ("strict" in requests[-1]["tools"][0]["function"]) == strict
        assert client.client.max_retries == 0


def test_provider_rejects_parameter_no_silent_retry(corpus):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(400, json={"error": {"message": "strict unsupported", "type": "invalid_request_error"}})
    client = transport_client(handler)
    result, trace = Agent(corpus, client).run("正式员工远程办公？", as_of=AS_OF)
    assert result["status"] == "FAILED" and len(requests) == 1
    assert not trace["steps"]


def test_provider_ignores_strict_and_parallel_local_validation_still_runs(corpus):
    def handler(request):
        return httpx.Response(200, json={"id": "x", "object": "chat.completion", "created": 0,
          "model": "synthetic-model", "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
          "role": "assistant", "tool_calls": [
            {"id": "x1", "type": "function", "function": {"name": "read_doc", "arguments": '{"doc_id":77}'}},
            {"id": "x2", "type": "function", "function": {"name": "search_docs", "arguments": '{}'}}]}}]})
    client = transport_client(handler)
    result, trace = Agent(corpus, client, max_steps=1).run("正式员工远程办公？", as_of=AS_OF)
    assert result["status"] == "INCOMPLETE"
    assert client.capabilities["parallel_constraint"] == "violated"
    assert all(not step["executed"] and step["observation"]["error_type"] == "INVALID_ARGUMENTS" for step in trace["steps"])


def test_malformed_provider_response_fails_without_fake_trace(corpus):
    def handler(request):
        return httpx.Response(200, json={"choices": []})
    result, trace = Agent(corpus, transport_client(handler)).run("正式员工远程办公？", as_of=AS_OF)
    assert result["status"] == "FAILED" and not trace["steps"]


def test_non_thinking_configuration_is_explicit_and_recorded(corpus):
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "x", "object": "chat.completion", "created": 0,
            "model": "synthetic-model", "choices": [{"index": 0, "finish_reason": "stop",
            "message": {"role": "assistant", "content": "plain text"}}]})
    for effort in (None, "none"):
        client = transport_client(handler, reasoning_effort=effort, strict=False, disable_parallel=False)
        _, trace = Agent(corpus, client, max_steps=1).run("正式员工远程办公？", as_of=AS_OF)
        assert ("reasoning_effort" in requests[-1]) == (effort is not None)
        assert requests[-1].get("reasoning_effort") == effort
        assert trace["config"]["reasoning_effort"] == effort
        assert "parallel_tool_calls" not in requests[-1]


def test_environment_reasoning_configuration_reaches_client(monkeypatch):
    from src import main
    received = {}
    def fake_client(*args, **kwargs):
        received.update(kwargs)
        return object()
    monkeypatch.setenv("MODEL_REASONING_EFFORT", "none")
    monkeypatch.setattr(main, "LiveClient", fake_client)
    main.live_client(strict=False, disable_parallel=False)
    assert received["reasoning_effort"] == "none"


def test_thinking_mode_is_not_silently_enabled():
    with pytest.raises(ValueError, match="思考模式"):
        LiveClient("synthetic-test-key", "synthetic-model", reasoning_effort="high")
