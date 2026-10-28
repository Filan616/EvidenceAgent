"""Create explicitly scripted offline inputs, never generated execution evidence."""
import json
from pathlib import Path

from src.llm_client import assistant, call
from src.rules import Corpus
from tests.helpers import args, contract, submission, normal_script, conflict_script, missing_script


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    corpus = Corpus.load("data/documents.json")
    normal = normal_script(corpus)
    failure = [normal[0], assistant(call("search_docs", args(query="正式员工远程办公", top_k=5), "retry")), *normal[1:]]
    always = [normal[0], assistant(call("submit_answer", submission(corpus, (), "FAILED"), "fail"))]
    history = [{"role": "user", "content": "正式员工远程办公有什么规定？"},
               {"role": "assistant", "content": "上一轮回答仅作话题上下文，本轮须重新读取制度。"}]
    context = [assistant(call("search_docs", args(query="试用期远程办公", top_k=5,
                          question_contract=contract("remote_work", "probation", None)), "h1")),
               assistant(call("read_doc", args(doc_id="D04"), "h2")),
               assistant(call("submit_answer", submission(corpus, ("D04-R1",)), "h3"))]
    scripts = {"normal": normal, "conflict": conflict_script(corpus), "missing": missing_script(corpus),
               "failure": failure, "always": always, "context": context,
               "similar": normal_script(corpus)}
    for name, script in scripts.items():
        save(Path(f"examples/mock_scripts/{name}.json"), {"mode": "mock", "description": "预设回放，仅验证执行器；不证明模型能力", "responses": script})
    save(Path("examples/context_history.json"), history)
    cases = [
        ("C01", "normal", "正式员工一周最多远程办公几天？", "COMPLETED", ["读取D03", "MAX 2 days/每周"]),
        ("C02", "conflict", "差旅费用最晚什么时候报销？", "NEEDS_CLARIFICATION", ["读取D01/D02", "无日期优先"]),
        ("C03", "missing", "公司今年利润是多少？", "INSUFFICIENT_EVIDENCE", ["无企业事实臆造"]),
        ("C04", "similar", "正式员工一周在家上班最多能申请几天？", "COMPLETED", ["D03", "是否改写按真实Trace记录"]),
        ("C05", "context", "那试用期呢？", "COMPLETED", ["历史定位话题", "读取D04", "不得套用正式额度"]),
        ("C06", "failure", "正式员工一周最多远程办公几天？", "COMPLETED", ["一次失败observation", "恢复后读取"]),
        ("C06B", "always", "正式员工一周最多远程办公几天？", "FAILED", ["持续失败", "无伪造成功"]),
    ]
    save(Path("examples/cases.json"), [{"id": cid, "script": name, "question": question,
         "expected_status": status, "checks": checks, "as_of": "2026-10-28",
         "history_file": "examples/context_history.json" if cid == "C05" else None,
         "fault": "search_docs:once" if cid == "C06" else ("search_docs:always" if cid == "C06B" else None)}
         for cid, name, question, status, checks in cases])


if __name__ == "__main__":
    main()
