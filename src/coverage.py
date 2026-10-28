"""Bounded coverage checks, never a mechanism for choosing tools."""
import copy
import re
from datetime import date

from .rules import scope_set
from .contracts import CONDITIONS, issue, normalize_contract

# Only validate explicit user constraints. These expressions never dispatch a tool.
TOPICS = {
    "remote_work": r"远程|在家(?:工作|上班)|居家办公",
    "travel_reimbursement": r"(?:差旅|出差|报销).*(?:期限|最晚|几天|多久|时间|什么时候|何时)",
    "annual_leave": r"年假",
    "reimbursement_receipts": r"票据|发票",
    "information_security": r"账号|凭证",
}


def explicit_scopes(text):
    scopes = []
    if re.search(r"正式(?:员工|职工)?", text):
        scopes.append("regular")
    if re.search(r"试用期", text):
        scopes.append("probation")
    if re.search(r"全体员工|所有员工", text):
        return {"regular", "probation"}
    return set(scopes)


class Coverage:
    def __init__(self, question, history, as_of):
        self.question = question
        self.history = history
        self.as_of = as_of
        self.contract = None
        self.revisions = []
        self.attempts = []
        self.field_errors = []
        self.hard_constraints = self._extract_constraints()
        self.provenance = []

    def _extract_constraints(self):
        """Extract only bounded, explicit input facts; never freeze model guesses."""
        source = self.question
        topic_source = "user"
        if not any(re.search(p, source) for p in TOPICS.values()) and re.search(r"那|呢", source):
            previous = next((m["content"] for m in reversed(self.history) if m["role"] == "user"), "")
            topic_text, topic_source = previous, "history_user"
        else:
            topic_text = source
        constraints = [{"field": "as_of", "value": self.as_of, "source": "runtime", "evidence": "--as-of", "protected": True}]
        topics = [g for g, p in TOPICS.items() if re.search(p, topic_text)]
        for group in topics:
            constraints.append({"field": "rule_group", "value": group, "source": topic_source,
                                "evidence": topic_text, "protected": True})
        scopes = explicit_scopes(source)
        scope_source, scope_evidence = "user", source
        if not scopes and topic_source == "history_user":
            scopes = explicit_scopes(topic_text)
            scope_source, scope_evidence = "history_user", topic_text
        if scopes:
            constraints.append({"field": "scope", "value": sorted(scopes), "source": scope_source, "evidence": scope_evidence, "protected": True})
        for canonical, pattern in [("每周", r"每周|一周"), ("每月", r"每月"), ("每年", r"每年")]:
            match = re.search(pattern, source)
            if match:
                constraints.append({"field": "period", "value": canonical, "source": "user", "evidence": match.group(), "protected": True})
        for event in ("差旅结束后", "差旅结束前", "出差结束后", "出差结束前"):
            if event in source:
                constraints.append({"field": "reference_event", "value": event.replace("出差", "差旅"), "source": "user", "evidence": event, "protected": True})
        for alias, canonical in CONDITIONS.items():
            if alias in source:
                constraints.append({"field": "conditions", "value": canonical, "source": "user", "evidence": alias, "protected": True})
        kind = "MIN" if re.search(r"最少|至少|下限", source) else ("MAX" if re.search(r"最多|上限", source) else None)
        if kind:
            constraints.append({"field": "constraint_type", "value": kind, "source": "user", "evidence": source, "protected": True})
        return constraints

    def _provenance(self, contract):
        result = []
        for index, req in enumerate(contract["requirements"]):
            for field, value in req.items():
                origins = [c for c in self.hard_constraints if c["field"] == field]
                if field == "conditions":
                    for condition_index, condition in enumerate(value):
                        matches = [c for c in origins if c["value"] == condition]
                        result.append({"field": f"requirements.{index}.conditions.{condition_index}", "value": condition,
                                       "source": [c["source"] for c in matches] or ["model"],
                                       "evidence": [c["evidence"] for c in matches], "protected": bool(matches)})
                    continue
                result.append({"field": f"requirements.{index}.{field}", "value": copy.deepcopy(value),
                               "source": [c["source"] for c in origins] or ["model"],
                               "evidence": [c["evidence"] for c in origins], "protected": bool(origins)})
        result.append({"field": "ambiguous", "value": contract["ambiguous"], "source": ["model"],
                       "evidence": [], "protected": False})
        return result

    def _facets(self, group):
        """Attach explicit subquestion facets to their topic, not every topic."""
        facets, current_groups = set(), set()
        for clause in re.split(r"[，,；;。？?]|以及|并且|同时", self.question):
            mentioned = {key for key, pattern in TOPICS.items() if re.search(pattern, clause)}
            if mentioned:
                current_groups = mentioned
            if group not in current_groups:
                continue
            if re.search(r"几天|多少天|最多|最少|至少|几次|额度|最晚|期限|多久", clause):
                facets.add("limit")
            if re.search(r"如何(?:申请|审批|办理)|怎么(?:申请|审批|办理)|审批流程", clause):
                facets.add("procedure")
            if re.search(r"必要条件|什么条件|哪些材料|什么票据", clause):
                facets.add("requirements")
        return facets

    def accept(self, contract):
        self.field_errors = []
        if contract is None:
            return [] if self.contract else ["首次工具调用必须提供 question_contract"]
        raw_contract = copy.deepcopy(contract)
        normalized, transformations, normalization_errors = normalize_contract(contract)
        contract = normalized["question_contract"]
        if normalization_errors:
            self.field_errors = normalization_errors
            self.attempts.append({"raw": raw_contract, "normalized": contract, "accepted": False,
                                  "normalization": transformations, "field_errors": normalization_errors})
            return [e["expected_semantics"] for e in normalization_errors]
        problems = []
        requirements = contract["requirements"]
        user_scopes = explicit_scopes(self.question)
        declared_scopes = set().union(*(scope_set(r["scope"]) for r in requirements))
        if user_scopes and user_scopes != declared_scopes:
            problems.append("question_contract 必须保留问题明确的员工范围，不能扩大或替换")
        for req in requirements:
            try:
                date.fromisoformat(req["as_of"])
            except ValueError:
                problems.append("question_contract 日期无效")
            if req["as_of"] != self.as_of:
                problems.append("问题适用日期必须与本次 --as-of 一致")
        explicit_dates = re.findall(r"\d{4}-\d{2}-\d{2}", self.question)
        if explicit_dates and any(d != self.as_of for d in explicit_dates) and not contract["ambiguous"]:
            problems.append("问题日期与 --as-of 不一致，需明确确认后重新运行")
        groups = {r["rule_group"] for r in requirements}
        explicit_topics = {group for group, pattern in TOPICS.items() if re.search(pattern, self.question)}
        scope_anchor = user_scopes
        if not scope_anchor and re.search(r"那|呢", self.question) and self.history:
            previous_user = next((m["content"] for m in reversed(self.history) if m["role"] == "user"), "")
            scope_anchor = explicit_scopes(previous_user)
        if re.search(r"实习|外包|兼职|派遣|供应商", self.question) and not contract["ambiguous"]:
            problems.append("问题员工类型超出受控分类，须请求澄清")
        if "remote_work" in groups and not scope_anchor and not contract["ambiguous"]:
            if any(scope_set(r["scope"]) != {"regular", "probation"}
                   for r in requirements if r["rule_group"] == "remote_work"):
                problems.append("问题未指定员工类型，不能擅自补成正式或试用期员工")
            if re.search(r"最多|几天|几次|额度|至少|最少", self.question):
                problems.append("未指定员工类别的额度问题需先澄清")
        for group, pattern in TOPICS.items():
            if re.search(pattern, self.question) and group not in groups:
                problems.append("问题显式主题未覆盖：" + group)
        # A short follow-up inherits topic, never scope, from user history.
        if not any(re.search(pattern, self.question) for pattern in TOPICS.values()):
            if re.search(r"那|呢", self.question) and self.history:
                previous = next((m["content"] for m in reversed(self.history) if m["role"] == "user"), "")
                for group, pattern in TOPICS.items():
                    if re.search(pattern, previous) and group not in groups:
                        problems.append("历史追问主题未覆盖：" + group)
                explicit_topics = {group for group, pattern in TOPICS.items() if re.search(pattern, previous)}
            if not explicit_topics and groups != {"unknown"} and not contract["ambiguous"]:
                problems.append("超出受控问题表达，不能确定性确认主题；应标记意图待澄清或 unknown")
        if "每周" in self.question or "一周" in self.question:
            if any(r["rule_group"] == "remote_work" and r["period"] != "每周" for r in requirements):
                problems.append("问题每周周期未保留")
        for phrase in ("每月", "每年"):
            if phrase in self.question and any(r["period"] != phrase for r in requirements if r["rule_group"] == "remote_work"):
                problems.append("问题周期未保留：" + phrase)
        for event in ("差旅结束后", "差旅结束前"):
            if event in self.question and any(r["reference_event"] != event for r in requirements if r["rule_group"] == "travel_reimbursement"):
                problems.append("问题参考事件未保留")
        expected_kind = None
        if re.search(r"最少|至少|下限", self.question):
            expected_kind = "MIN"
        elif re.search(r"最多|上限", self.question):
            expected_kind = "MAX"
        if expected_kind and any(r["constraint_type"] != expected_kind for r in requirements if r["rule_group"] == "remote_work"):
            problems.append("问题的上下限语义未保留")
        # revision_reason is audit text, not an immutable semantic constraint.
        old_semantics = {k: v for k, v in (self.contract or {}).items() if k != "revision_reason"}
        new_semantics = {k: v for k, v in contract.items() if k != "revision_reason"}
        if self.contract and new_semantics != old_semantics:
            if not contract["revision_reason"].strip():
                problems.append("修订问题解释必须说明原因")
        for constraint in self.hard_constraints:
            if constraint["field"] == "conditions" and not all(constraint["value"] in r["conditions"] for r in requirements):
                problems.append("用户明确的必要条件不得删除：" + constraint["value"])
            if constraint["field"] == "scope" and scope_set(constraint["value"]) != declared_scopes:
                problems.append("用户或历史明确的员工范围不得替换")
        if not problems:
            if self.contract != contract:
                self.revisions.append(copy.deepcopy(contract))
            self.contract = copy.deepcopy(contract)
            self.provenance = self._provenance(contract)
        else:
            self.field_errors = self._contract_feedback(problems, contract)
        self.attempts.append({"raw": raw_contract, "normalized": copy.deepcopy(contract), "accepted": not problems,
                              "normalization": transformations, "field_errors": copy.deepcopy(self.field_errors),
                              "provenance": self._provenance(contract)})
        return problems

    def _contract_feedback(self, problems, contract):
        errors = []
        for problem in problems:
            field = next((field for word, field in [("周期", "period"), ("员工范围", "scope"), ("员工类型", "scope"),
                          ("参考事件", "reference_event"), ("日期", "as_of"), ("上下限", "constraint_type"),
                          ("必要条件", "conditions"), ("主题", "rule_group"), ("修订", "revision_reason")] if word in problem), "ambiguous")
            origins = [c for c in self.hard_constraints if c["field"] == field]
            actual = contract.get(field) if field in contract else [r.get(field) for r in contract["requirements"]]
            expected = [c["value"] for c in origins] or problem
            errors.append(issue("USER_CONSTRAINT_VIOLATION" if origins else "CONTRACT_REVISION_REQUIRED",
                                "question_contract." + field, actual, expected,
                                [problem, "保留用户硬约束；模型推断可提供revision_reason后修正；后续无变更传null"],
                                "user_or_runtime" if origins else "model"))
        return errors

    def check(self, claims, rules, corpus):
        self.field_errors = []
        if self.contract["ambiguous"]:
            self.field_errors = [issue("UNRESOLVED_MODEL_AMBIGUITY", "question_contract.ambiguous", True,
                                      "是否存在会改变答案且未能由已读证据解决的适用歧义",
                                      ["若已读规则覆盖全部员工且结论一致，可说明原因修订ambiguous=false", "若仍影响答案，请求用户澄清"])]
            return ["用户意图或适用条件不明确，应请求澄清"]
        problems = []
        for index, req in enumerate(self.contract["requirements"]):
            relevant = [r for r in rules if r["rule_group"] == req["rule_group"]]
            if not relevant:
                problems.append("未覆盖问题规则组：" + req["rule_group"])
                continue
            facets = {r["facet"] for r in [req] if r["facet"] != "all"}
            facets.update(self._facets(req["rule_group"]))
            supported_facets = set().union(*(set(r["facets"]) for r in relevant))
            if not facets <= supported_facets:
                problems.append("证据未覆盖所问额度、流程或必要条件")
            if req["constraint_type"] and not any(r["constraint_type"] == req["constraint_type"] for r in relevant):
                problems.append("证据未覆盖问题的约束类型")
            wanted = scope_set(req["scope"])
            covered = set().union(*(scope_set(r["scope"]) for r in relevant))
            if not wanted <= covered:
                problems.append("问题适用范围未完整覆盖")
            for field in ("period", "reference_event"):
                if req[field] is not None and not any(r[field] == req[field] for r in relevant):
                    problems.append("问题约束未覆盖：" + field)
                    self.field_errors.append(issue("UNCOVERED_CONSTRAINT", f"question_contract.requirements.{index}.{field}",
                        req[field], {"read_rule_values": [r[field] for r in relevant], "meaning": "period为周期，reference_event仅为截止起算事件"},
                        ["用户明示约束不能删除；模型自行推断的字段可带revision_reason修正后重新提交", "不得修改claims来迎合错误契约"]))
            if req["conditions"] and not any(set(req["conditions"]) <= set(r["conditions"]) for r in relevant):
                problems.append("问题必要条件未覆盖")
                self.field_errors.append(issue("UNCOVERED_CONDITION", f"question_contract.requirements.{index}.conditions",
                    req["conditions"], {"read_rule_conditions": [r["conditions"] for r in relevant], "scope": req["scope"]},
                    ["员工类别归scope；用户未提出的推断条件可说明原因移除；用户明确条件必须保留"]))
            applicable = corpus.applicable(req["rule_group"], req["scope"], req["as_of"])
            # Complete answers include every applicable, non-superseded rule in the
            # requested group: prevents omitting approval conditions and subclauses.
            if not {r["rule_id"] for r in applicable} <= {r["rule_id"] for r in relevant}:
                problems.append("遗漏适用条款或必要条件")
        allowed = {r["rule_group"] for r in self.contract["requirements"]}
        if any(r["rule_group"] not in allowed for r in rules):
            problems.append("包含未被用户问题要求的规则组")
        return problems
