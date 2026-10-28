"""CLI entry point. Defaults to a real provider; configuration errors never use Mock."""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

from .agent import Agent
from .llm_client import LiveClient, ScriptedClient
from .rules import Corpus
from .trace import write_json

ROOT = Path(__file__).resolve().parents[1]


def today():
    try:
        return datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    except ZoneInfoNotFoundError:
        from datetime import timezone, timedelta
        return datetime.now(timezone(timedelta(hours=8))).date().isoformat()


def parser():
    p = argparse.ArgumentParser(description="EvidenceAgent：基于合成制度的可溯源 CLI 问答")
    p.add_argument("--question", required=True)
    p.add_argument("--history-file", type=Path)
    p.add_argument("--documents-file", type=Path, default=ROOT / "data/documents.json")
    p.add_argument("--trace-file", type=Path)
    p.add_argument("--output-file", type=Path)
    p.add_argument("--fault", choices=["search_docs:once", "search_docs:always"])
    p.add_argument("--mock", action="store_true", help="仅回放显式离线脚本，不能证明真实模型决策")
    p.add_argument("--mock-script", type=Path, default=ROOT / "examples/mock_scripts/normal.json")
    p.add_argument("--max-steps", type=int)
    p.add_argument("--max-tool-calls", type=int)
    p.add_argument("--as-of", default=today(), help="制度适用日期，默认 Asia/Shanghai 当天")
    p.add_argument("--no-strict-tools", action="store_true", help="显式兼容：移除 strict；本地校验仍启用")
    p.add_argument("--allow-parallel-tools", action="store_true", help="显式兼容：不发送 parallel_tool_calls 参数")
    return p


def env_bool(name, default=True):
    value = os.getenv(name, str(default)).lower()
    if value not in {"true", "false"}:
        raise ValueError(f"{name} 必须为 true 或 false")
    return value == "true"


def history_from(path):
    history = json.loads(path.read_text(encoding="utf-8")) if path else []
    if not isinstance(history, list) or any(not isinstance(m, dict) or set(m) != {"role", "content"}
            or m["role"] not in {"user", "assistant"} or not isinstance(m["content"], str)
            for m in history):
        raise ValueError("历史须为仅含 user/assistant 的 role/content 消息数组")
    return history


def live_client(strict=None, disable_parallel=None):
    return LiveClient(os.getenv("OPENAI_API_KEY"), os.getenv("MODEL_NAME"), os.getenv("OPENAI_BASE_URL") or None,
                      env_bool("STRICT_TOOLS") if strict is None else strict,
                      env_bool("DISABLE_PARALLEL") if disable_parallel is None else disable_parallel,
                      reasoning_effort=os.getenv("MODEL_REASONING_EFFORT") or None)


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    load_dotenv(ROOT / ".env")
    try:
        if not args.question.strip():
            raise ValueError("question 不能为空")
        date.fromisoformat(args.as_of)
        steps = args.max_steps if args.max_steps is not None else int(os.getenv("MAX_STEPS", "8"))
        calls = args.max_tool_calls if args.max_tool_calls is not None else int(os.getenv("MAX_TOOL_CALLS", "10"))
        corpus = Corpus.load(args.documents_file)
        history = history_from(args.history_file)
        if args.mock:
            script = json.loads(args.mock_script.read_text(encoding="utf-8"))
            if script.get("mode") != "mock" or not isinstance(script.get("responses"), list):
                raise ValueError("Mock 脚本必须显式标记 mode=mock 并提供 responses")
            client = ScriptedClient(script["responses"])
        else:
            client = live_client(strict=False if args.no_strict_tools else None,
                                 disable_parallel=False if args.allow_parallel_tools else None)
        trace_path = args.trace_file or ROOT / "examples/generated" / client.mode / (uuid.uuid4().hex + "_trace.json")
        stem = trace_path.stem.removesuffix("_trace")
        output_path = args.output_file or trace_path.with_name(stem + "_output.json")
        input_path = trace_path.with_name(stem + "_input.json")
        paths = [trace_path, output_path, input_path]
        if len({path.resolve() for path in paths}) != 3:
            raise ValueError("输入记录、输出和 Trace 路径不能相同")
        protected = {args.documents_file.resolve()}
        if args.history_file:
            protected.add(args.history_file.resolve())
        if any(path.resolve() in protected for path in paths):
            raise ValueError("输出不能覆盖语料或历史文件")
        provider = urlsplit(os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").hostname if not args.mock else "mock"
        agent = Agent(corpus, client, steps, calls, args.fault, {"provider_host": provider,
                      "strict_requested": client.strict, "parallel_constraint_requested": getattr(client, "disable_parallel", None)})
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"配置/输入错误：{exc}", file=sys.stderr)
        return 2
    result, trace = agent.run(args.question, history, args.as_of)
    result["trace_path"] = str(trace_path)
    try:
        write_json(input_path, {**trace["input"], "as_of": args.as_of, "mode": client.mode, "corpus_hash": corpus.hash})
        write_json(trace_path, trace)
        write_json(output_path, result)
    except (OSError, ValueError) as exc:
        print(f"保存失败：{exc}；未确认全部文件保存成功。", file=sys.stderr)
        return 1
    print(f"状态：{result['status']} ({client.mode})\n回答：{result['answer']}")
    print("引用：" + (", ".join(c["doc_id"] for c in result["citations"]) or "无"))
    print(f"Trace：{trace_path}\n输出：{output_path}")
    if result["gaps"]:
        print("缺口：" + "；".join(result["gaps"]))
    return 1 if result["status"] in {"FAILED", "INCOMPLETE"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
