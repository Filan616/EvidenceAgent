"""Evaluation helpers operate on completed traces; never influence the executor."""
import copy

from .rules import Corpus, render_rule

FIXED_AS_OF = "2026-10-28"


def mutate(corpus, variant):
    data = copy.deepcopy(corpus.data)
    documents = data["documents"]
    if variant == "T02":
        doc = next(d for d in documents if d["doc_id"] == "D03")
        rule = doc["rules"][0]
        old = rule["evidence"]
        rule["value"] = 1
        rule["evidence"] = render_rule(rule)
        doc["content"] = doc["content"].replace(old, rule["evidence"])
    elif variant == "T04":
        doc = next(d for d in documents if d["doc_id"] == "D02")
        rule = doc["rules"][0]
        old = rule["evidence"]
        rule["value"] = 30
        rule["evidence"] = render_rule(rule)
        doc["content"] = doc["content"].replace(old, rule["evidence"])
    elif variant == "T05":
        data["documents"] = [d for d in documents if d["doc_id"] not in {"D03", "D04"}]
    elif variant not in {"T01", "T03", "T06"}:
        raise ValueError("未知变异测试")
    return Corpus(data)


def executed_searches(trace):
    """Only real business execution, never schema/contract rejection observations."""
    return [s for s in trace["steps"] if s.get("executed") is True and s["action"] == "search_docs"
            and (s["observation"].get("ok") is True or s["observation"].get("error_type") in {"INJECTED_FAILURE", "TOOL_ERROR"})]


def live_path_errors(trace, corpus, fault=None):
    """Independent evaluation prerequisites; no influence on agent decisions."""
    problems = []
    if trace["mode"] != "live" or trace["model"] == "mock":
        problems.append("不是实际Live模式")
    if trace["corpus_hash"] != corpus.hash or trace["config"]["as_of"] != FIXED_AS_OF:
        problems.append("语料快照或固定日期不匹配")
    steps = trace["steps"]
    business = [s for s in steps if s.get("executed") and s["action"] in {"search_docs", "read_doc"}]
    if not business or trace["counts"]["model_calls"] < 2:
        problems.append("未完成实际业务工具执行及观察后的模型轮次")
    reads = {s["observation"]["doc_id"]: s["observation"] for s in business
             if s["action"] == "read_doc" and s["observation"].get("ok")}
    final = trace["final"]
    for citation in final["citations"]:
        from .rules import normalize
        doc = reads.get(citation["doc_id"])
        if not doc or not citation["quote"].strip() or normalize(citation["quote"]) not in normalize(doc["content"]):
            problems.append("最终引用没有本次实际成功读取的原文支持")
    if final["status"] in {"COMPLETED", "NEEDS_CLARIFICATION", "INSUFFICIENT_EVIDENCE"}:
        if not any(s["action"] == "submit_answer" and s.get("executed") and s["observation"].get("ok") for s in steps):
            problems.append("业务结果缺少实际通过校验的终止提交")
    searches = executed_searches(trace)
    if final["status"] == "INSUFFICIENT_EVIDENCE" and not any(s["observation"]["ok"] for s in searches):
        problems.append("证据不足结论之前没有真实成功检索")
    if fault:
        faults = [s for s in searches if s["observation"].get("error_type") == "INJECTED_FAILURE"]
        if not faults:
            problems.append("未实际触发并观察注入工具故障")
        if fault == "search_docs:always" and any(s["observation"]["ok"] for s in searches):
            problems.append("持续故障模式出现了不应成功的检索")
        if fault == "search_docs:once" and final["status"] == "COMPLETED":
            if not faults or not any(s["observation"]["ok"] and s["step"] > faults[0]["step"] for s in searches):
                problems.append("一次故障后的完成结果缺少真实成功检索恢复")
    return problems


def action_after_search(trace, *, error_type=None):
    steps = trace["steps"]
    eligible = executed_searches(trace)
    for step in eligible:
        if (step["observation"].get("error_type") == error_type if error_type else step["observation"]["ok"]):
            # A call selected in the same parallel batch cannot have observed this result.
            nxt = next((s for s in steps if s["step"] > step["step"] and s.get("executed")
                        and s.get("round", s["step"]) > step.get("round", step["step"])), None)
            if nxt is None:
                continue
            return {"observation_call_id": step["call_id"], "observation_ok": step["ok"],
                    "observation": copy.deepcopy(step["observation"]),
                    "next_call_id": nxt["call_id"], "action": nxt["action"],
                    "parameters": {k: v for k, v in nxt["parameters"].items()
                                   if k not in {"reason", "question_contract"}}}
    return None


def compare_decisions(normal, changed):
    if normal["mode"] != "live" or changed["mode"] != "live":
        return {"passed": False, "reason": "Mock 不能证明真实模型动态决策"}
    if normal["input"] != changed["input"] or normal["requested_model"] != changed["requested_model"]:
        return {"passed": False, "reason": "对照要求相同输入及请求模型"}
    if normal["final"]["status"] != "COMPLETED" or changed["final"]["status"] not in {"COMPLETED", "FAILED"}:
        return {"passed": False, "reason": "对照业务结果未达到原有验收标准"}
    a, b = action_after_search(normal), action_after_search(changed, error_type="INJECTED_FAILURE")
    passed = bool(a and b and a["observation_ok"] != b["observation_ok"] and
                  (a["action"], a["parameters"]) != (b["action"], b["parameters"]))
    return {"passed": passed, "normal": a, "changed": b,
            "reason": "实际 observation 与后续工具决策不同" if passed else "未观察到所需的不同后续动作；不能仅以答案不同证明"}
