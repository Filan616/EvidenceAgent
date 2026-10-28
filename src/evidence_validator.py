"""Grounding and coverage gates for the controlled corpus, not general entailment."""
import copy
from itertools import combinations

from .rules import active, normalize, render_rule, scope_set
from .tools import error
from .contracts import issue, normalize_arguments

SEMANTIC_FIELDS = ("scope", "constraint_type", "operator", "value", "unit", "period",
                   "reference_event", "conditions", "effective_from", "effective_to")


def claim_for(rule, doc_id):
    """Fixture/helper: construct an extractive claim from a real loaded rule."""
    return {"statement": render_rule(rule), "evidence_doc_id": doc_id,
            "evidence_quote": rule["evidence"], "rule_id": rule["rule_id"],
            **{field: rule[field] for field in SEMANTIC_FIELDS}}


class EvidenceValidator:
    def __init__(self, corpus, tools, coverage):
        self.corpus, self.tools, self.coverage = corpus, tools, coverage

    def validate(self, submission):
        submission, _, normalization_errors = normalize_arguments(submission)
        if normalization_errors:
            return error("NORMALIZATION_ERROR", "声明存在字段语义冲突", field_errors=normalization_errors)
        problems, validated, citations = [], [], []
        field_errors = []
        status, claims = submission["status"], submission["claims"]
        contract = self.coverage.contract
        if not contract:
            return error("VALIDATION_ERROR", "缺少有效问题解释", details=["QUESTION_CONTRACT_REQUIRED"])
        for claim in claims:
            did, rid, quote = claim["evidence_doc_id"], claim["rule_id"], claim["evidence_quote"]
            doc, rule = self.tools.read.get(did), self.corpus.rules.get(rid)
            if doc is None or rule is None or self.corpus.rule_docs.get(rid) != did:
                problems.append("引用文档未成功读取或条款 ID 无效")
                continue
            if not quote.strip() or normalize(quote) not in normalize(doc["content"]):
                problems.append("引用不是对应正文的真实片段")
            if normalize(rule["evidence"]) not in normalize(quote):
                problems.append("引用未完整包含规则及必要条件")
            mismatches = [field for field in SEMANTIC_FIELDS if field != "scope"
                          and (set(claim[field]) != set(rule[field]) if field == "conditions" else claim[field] != rule[field])]
            if mismatches:
                problems.append("声明语义字段与规则不一致")
                for field in mismatches:
                    field_errors.append(issue("CLAIM_RULE_MISMATCH", f"claims.{len(validated)}.{field}", claim[field], rule[field],
                                              ["按已经读取的原文和规则修正声明；不得修改原文或规则来通过校验"], "read_document"))
            if not scope_set(claim["scope"]) <= scope_set(rule["scope"]):
                problems.append("声明扩大了制度适用范围")
            rendered_rule = {**copy.deepcopy(rule), "scope": claim["scope"]}
            if normalize(claim["statement"]) != normalize(render_rule(rendered_rule)):
                problems.append("声明非受控模板或原文摘录")
            matching = [req for req in contract["requirements"] if req["rule_group"] == rule["rule_group"]
                        and scope_set(req["scope"]) & scope_set(rule["scope"])]
            if not matching or not any(active(rule, req["as_of"]) for req in matching):
                problems.append("声明不适用于问题的规则、范围或时间")
            for req in matching:
                applicable = self.corpus.applicable(req["rule_group"], req["scope"], req["as_of"])
                if rid not in {r["rule_id"] for r in applicable}:
                    problems.append("引用条款已被明确覆盖")
                for other in self.corpus.rules.values():
                    for leaf in scope_set(claim["scope"]) & scope_set(rule["scope"]):
                        if self.corpus.supersedes(other["rule_id"], rid, req["as_of"], {leaf}):
                            problems.append("声明范围包含已被其他条款明确覆盖的员工类型")
            # Text rules cannot safely change their subject by changing metadata alone.
            if isinstance(rule["value"], str) and claim["scope"] != rule["scope"]:
                problems.append("摘录型声明必须保留原文范围")
            validated.append(rendered_rule)
            citation = {"doc_id": did, "quote": quote}
            if citation not in citations:
                citations.append(citation)
        if submission["citations"] != citations:
            problems.append("citations 必须与 claims 证据去重结果一致")

        conflict_pairs, uncertain_pairs = [], []
        for req in contract["requirements"]:
            rules = self.corpus.applicable(req["rule_group"], req["scope"], req["as_of"])
            for a, b in combinations(rules, 2):
                relation = self.corpus.relation(a, b, req["as_of"], req["scope"])
                pair = (a["rule_id"], b["rule_id"])
                if relation == "conflict" and pair not in conflict_pairs:
                    conflict_pairs.append(pair)
                if relation == "uncertain" and pair not in uncertain_pairs:
                    uncertain_pairs.append(pair)
        # Only expose IDs and gaps. Never expose unread content or values.
        conflict_ids = sorted({self.corpus.rule_docs[rid] for pair in conflict_pairs for rid in pair})
        all_pairs = conflict_pairs + uncertain_pairs
        if all_pairs and status == "COMPLETED":
            problems.append("存在冲突或条件关系不明；需补充证据并澄清")
        if status == "NEEDS_CLARIFICATION":
            if not submission["gaps"]:
                problems.append("澄清必须说明缺口")
            if conflict_pairs:
                required = {rid for pair in conflict_pairs for rid in pair}
                if not required <= {r["rule_id"] for r in validated}:
                    problems.append("冲突双方尚未成功读取并引用")
                if not submission["conflicts"]:
                    problems.append("未列出已知冲突")
            elif not contract["ambiguous"] and not uncertain_pairs:
                problems.append("无冲突或条件歧义，不能用澄清状态掩盖证据缺失")
        coverage_problems = self.coverage.check(claims, validated, self.corpus)
        if status == "COMPLETED":
            if not claims:
                problems.append("COMPLETED 必须有有效事实声明")
            if submission["gaps"] or submission["conflicts"]:
                problems.append("存在缺口或冲突不能标记 COMPLETED")
            problems.extend(coverage_problems)
        if status in {"INSUFFICIENT_EVIDENCE", "FAILED", "INCOMPLETE"}:
            if claims or citations or submission["conflicts"]:
                problems.append("失败或证据不足状态不能携带确定性事实声明")
            if not submission["gaps"]:
                problems.append("未完成状态必须说明原因")
        if status == "INSUFFICIENT_EVIDENCE":
            if contract["ambiguous"] or all_pairs:
                problems.append("意图不明确或制度冲突应请求澄清")
            if not self.tools.successful_searches:
                problems.append("未成功检索不能将工具异常包装为证据不足")
        if status == "FAILED" and not self.tools.failures:
            problems.append("没有观察到工具失败，不能提交工具故障结论")
        if submission["conflicts"] and not conflict_pairs:
            problems.append("未发现元数据支持的冲突，不能声称冲突")
        if problems:
            return error("VALIDATION_ERROR", "终稿未通过校验，请根据缺口自行查证或修正",
                         details=sorted(set(problems)), related_doc_ids=sorted(set(conflict_ids + [
                             self.corpus.rule_docs[r] for pair in uncertain_pairs for r in pair])),
                         field_errors=field_errors + self.coverage.field_errors + (
                             [] if field_errors or self.coverage.field_errors else [issue("FINAL_VALIDATION_ERROR", "submit_answer", status,
                                 sorted(set(problems)), ["补齐已读证据，或修订模型推断并重新提交；用户硬约束不可删除"])]),
                         checks={"facts": not any("声明" in p or "引用" in p for p in problems),
                                 "coverage": not coverage_problems, "conflicts": not all_pairs})
        prefix = {"COMPLETED": "", "NEEDS_CLARIFICATION": "需要确认适用制度或条件。",
                  "INSUFFICIENT_EVIDENCE": "现有资料不足以回答该问题。",
                  "FAILED": "工具异常导致任务失败。", "INCOMPLETE": "任务尚未完成。"}[status]
        conflicts = [f"{self.corpus.rule_docs[a]} / {self.corpus.rule_docs[b]} 的适用条款存在冲突" for a, b in conflict_pairs]
        gaps = []
        if status == "NEEDS_CLARIFICATION":
            if conflict_pairs:
                gaps.append("缺少重叠适用条款之间的明确优先或覆盖依据。")
            if uncertain_pairs:
                gaps.append("条款的单位、周期、参考事件或条件关系需要确认。")
            if contract["ambiguous"]:
                gaps.append("需要确认问题意图、员工范围、适用日期或必要条件。")
        elif status == "INSUFFICIENT_EVIDENCE":
            gaps = ["已成功检索，但尚无足够的有效证据覆盖问题。"]
        elif status == "FAILED":
            gaps = ["已观察到工具异常，未获得可接受的恢复结果。"]
        elif status == "INCOMPLETE":
            gaps = ["模型通过结构化终止动作报告任务尚未完成。"]
        return {"ok": True, "result": {"status": status,
                "answer": prefix + "".join(render_rule(r) for r in validated),
                "claims": claims, "citations": citations, "gaps": gaps,
                "conflicts": conflicts}, "checks": {"facts": True, "coverage": not coverage_problems,
                                                       "conflicts_resolved": not all_pairs}}
