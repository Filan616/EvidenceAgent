"""Native Chat Completions client. Mock scripts are explicit, never question routers."""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass
class Reply:
    message: dict
    model: str


class LiveClient:
    mode = "live"

    def __init__(self, api_key, model, base_url=None, strict=True, disable_parallel=True,
                 transport=None, reasoning_effort=None):
        if not api_key or not model:
            raise ValueError("真实模式需要 OPENAI_API_KEY 和 MODEL_NAME；请在 .env 或环境变量配置，不会自动使用 Mock。")
        if reasoning_effort not in (None, "none"):
            raise ValueError("MODEL_REASONING_EFFORT 当前仅支持留空或 none；思考模式的多轮协议尚未实现。")
        from openai import OpenAI
        self.model = model
        self.strict = strict
        self.disable_parallel = disable_parallel
        self.reasoning_effort = reasoning_effort
        self.capabilities = {"native_tool_calling": "unknown", "strict_schema": "unknown" if strict else "disabled_explicitly",
                             "parallel_constraint": "unknown" if disable_parallel else "disabled_explicitly"}
        self.client = transport or OpenAI(api_key=api_key, base_url=base_url, max_retries=0, timeout=45)
        self.provider_host = urlsplit(str(self.client.base_url)).hostname

    def complete(self, messages, tools):
        request = {"model": self.model, "messages": messages, "tools": tools, "tool_choice": "auto"}
        if self.reasoning_effort is not None:
            request["reasoning_effort"] = self.reasoning_effort
        if self.disable_parallel:
            request["parallel_tool_calls"] = False
        try:
            response = self.client.chat.completions.create(**request)
        except Exception as exc:
            # No raw provider body: may echo request secrets or arbitrary data.
            status = getattr(exc, "status_code", None)
            raise RuntimeError(f"模型 API 错误 {type(exc).__name__}, HTTP={status}；检查服务商 Tool Calling/strict/parallel 能力及配置；不会静默降级。") from None
        if not response.choices:
            raise RuntimeError("模型返回空 choices")
        message = response.choices[0].message
        calls = message.tool_calls or []
        if calls:
            self.capabilities["native_tool_calling"] = "observed"
        if self.strict and self.capabilities["strict_schema"] != "violated":
            self.capabilities["strict_schema"] = "parameter_accepted_enforcement_unknown"
        if self.disable_parallel and len(calls) > 1:
            self.capabilities["parallel_constraint"] = "violated"
        elif self.disable_parallel and self.capabilities["parallel_constraint"] != "violated":
            self.capabilities["parallel_constraint"] = "parameter_accepted_no_violation_observed"
        # One successful response is not proof that a server enforces strict schemas.
        return Reply({"role": "assistant", "content": None,
                      "tool_calls": [{"id": call.id, "type": "function", "function": {
                          "name": call.function.name, "arguments": call.function.arguments}}
                                     for call in calls]}, response.model)


class ScriptedClient:
    mode = "mock"
    model = "mock"
    strict = True
    provider_host = "mock"
    capabilities = {"native_tool_calling": "mock_only", "strict_schema": "mock_only", "parallel_constraint": "mock_only"}

    def __init__(self, responses):
        self.responses = iter(copy.deepcopy(responses))
        self.messages = []

    def complete(self, messages, tools):
        self.messages.append(copy.deepcopy(messages))
        try:
            response = next(self.responses)
        except StopIteration:
            raise RuntimeError("Mock 脚本耗尽；不能推断后续模型动作") from None
        if isinstance(response, Exception):
            raise response
        return Reply(response, "mock")


def call(name, arguments, call_id):
    """Helper for test fixtures only."""
    return {"id": call_id, "type": "function", "function": {
        "name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}}


def assistant(*calls):
    return {"role": "assistant", "content": None, "tool_calls": list(calls)}
