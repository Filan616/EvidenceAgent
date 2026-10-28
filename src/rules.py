"""Small, deliberately bounded rule language. No tool routing lives here."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import date
from pathlib import Path

SCOPES = {"all_employees", "regular", "probation"}
OPERATORS = {"MAX": "<=", "MIN": ">=", "EXACT": "=", "DEADLINE": "<="}
RULE_FIELDS = {"rule_id", "rule_group", "scope", "effective_from", "effective_to",
               "operator", "constraint_type", "value", "unit", "reference_event",
               "period", "conditions", "supersedes", "evidence", "facets"}


def normalize(text):
    return re.sub(r"\s+", "", text)


def scope_set(scope):
    return {"regular", "probation"} if "all_employees" in scope else set(scope)


def active(rule, as_of):
    return rule["effective_from"] <= as_of and (
        rule["effective_to"] is None or as_of < rule["effective_to"])


def interval_overlap(a, b):
    return max(a["effective_from"], b["effective_from"]) < min(
        a["effective_to"] or "9999-12-31", b["effective_to"] or "9999-12-31")


def render_rule(rule):
    """Canonical numerical statements; textual EXACT rules are extractive."""
    value = rule["value"]
    if isinstance(value, str):
        return value
    scope = {"all_employees": "员工", "regular": "正式员工", "probation": "试用期员工"}
    subject = "、".join(scope[s] for s in rule["scope"])
    amount = format(value, "g")
    unit = {"days": "天", "times": "次"}[rule["unit"]]
    if rule["constraint_type"] == "DEADLINE":
        base = f"{subject}应在{rule['reference_event']}{amount}{unit}内提交报销申请。"
    else:
        modifier = {"MAX": "最多", "MIN": "至少", "EXACT": "固定"}[rule["constraint_type"]]
        base = f"{subject}{rule['period'] or ''}{modifier}可以申请{amount}{unit}远程办公。"
    if rule["conditions"]:
        base += "适用条件：" + "；".join(rule["conditions"]) + "。"
    return base


class Corpus:
    def __init__(self, data):
        self.data = copy.deepcopy(data)
        self.documents = {}
        self.rules = {}
        self.rule_docs = {}
        self.groups = self.data["rule_groups"]
        self._validate()
        self.hash = hashlib.sha256(json.dumps(self.data, ensure_ascii=False,
                                             sort_keys=True).encode()).hexdigest()

    @classmethod
    def load(cls, path):
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def _validate(self):
        if not isinstance(self.groups, dict):
            raise ValueError("rule_groups 必须为对象")
        for group in self.groups.values():
            if group["semantics"] not in {"functional", "bounds"}:
                raise ValueError("未知规则比较语义")
        for doc in self.data["documents"]:
            for field in ("doc_id", "title", "version_date", "scope", "content", "rules"):
                if field not in doc:
                    raise ValueError(f"文档缺少 {field}")
            if not isinstance(doc["doc_id"], str) or doc["doc_id"] in self.documents:
                raise ValueError("重复或无效文档 ID")
            date.fromisoformat(doc["version_date"])
            if not isinstance(doc["scope"], list) or not doc["scope"] or not set(doc["scope"]) <= SCOPES:
                raise ValueError("无效文档适用范围")
            if not isinstance(doc["content"], str) or not doc["content"].strip():
                raise ValueError("文档正文为空")
            self.documents[doc["doc_id"]] = doc
            for rule in doc["rules"]:
                if set(rule) != RULE_FIELDS:
                    raise ValueError("规则字段不完整或含未知字段")
                rid = rule["rule_id"]
                if not isinstance(rid, str) or not rid or rid in self.rules:
                    raise ValueError("重复或无效条款 ID")
                if rule["rule_group"] not in self.groups:
                    raise ValueError("未知规则组")
                if not rule["facets"] or not set(rule["facets"]) <= {"limit", "procedure", "requirements"}:
                    raise ValueError("无效条款问题类型 facets")
                if (not isinstance(rule["scope"], list) or not rule["scope"]
                        or not set(rule["scope"]) <= SCOPES):
                    raise ValueError("无效适用范围")
                if not scope_set(rule["scope"]) <= scope_set(doc["scope"]):
                    raise ValueError("条款范围超出文档范围")
                start = date.fromisoformat(rule["effective_from"])
                if rule["effective_to"] and date.fromisoformat(rule["effective_to"]) <= start:
                    raise ValueError("无效生效区间")
                if OPERATORS.get(rule["constraint_type"]) != rule["operator"]:
                    raise ValueError("operator 与 constraint_type 不一致")
                for field in ("conditions", "supersedes"):
                    if not isinstance(rule[field], list) or not all(isinstance(x, str) and x for x in rule[field]):
                        raise ValueError(f"无效 {field}")
                for field in ("period", "reference_event"):
                    if rule[field] is not None and (not isinstance(rule[field], str) or not rule[field]):
                        raise ValueError(f"无效 {field}")
                value = rule["value"]
                if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                    raise ValueError("无效规则值")
                if isinstance(value, str):
                    if rule["constraint_type"] != "EXACT" or rule["unit"] != "text" or not value:
                        raise ValueError("文本规则仅支持 EXACT/text")
                    if not all(normalize(c) in normalize(value) for c in rule["conditions"]):
                        raise ValueError("文本规则遗漏必要条件")
                else:
                    if value < 0 or value != value or value == float("inf"):
                        raise ValueError("数值必须有限且非负")
                    if rule["unit"] not in {"days", "times"}:
                        raise ValueError("未知数值单位")
                    if rule["constraint_type"] == "DEADLINE":
                        if not rule["reference_event"] or rule["period"] is not None:
                            raise ValueError("截止规则必须有参考事件且不能有周期")
                    elif rule["rule_group"] != "remote_work" or not rule["period"]:
                        raise ValueError("当前数值渲染仅支持远程办公周期或报销截止规则")
                if normalize(render_rule(rule)) != normalize(rule["evidence"]):
                    raise ValueError("规则语义与 evidence 不一致")
                if normalize(rule["evidence"]) not in normalize(doc["content"]):
                    raise ValueError("规则 evidence 不在正文中")
                self.rules[rid] = rule
                self.rule_docs[rid] = doc["doc_id"]
        for rule in self.rules.values():
            for target in rule["supersedes"]:
                other = self.rules.get(target)
                if (other is None or other["rule_group"] != rule["rule_group"]
                        or not scope_set(rule["scope"]) & scope_set(other["scope"])
                        or not interval_overlap(rule, other)):
                    raise ValueError("无效覆盖引用或覆盖范围/时间无交集")
        def visit(rid, stack):
            if rid in stack:
                raise ValueError("覆盖关系存在环")
            for target in self.rules[rid]["supersedes"]:
                visit(target, stack | {rid})
        for rid in self.rules:
            visit(rid, set())

    def supersedes(self, newer, older, as_of, scope):
        """Only active, applicable explicit paths establish precedence."""
        rule = self.rules[newer]
        if not active(rule, as_of) or not scope <= scope_set(rule["scope"]):
            return False
        return any(target == older or self.supersedes(target, older, as_of, scope)
                   for target in rule["supersedes"])

    def applicable(self, group, scopes, as_of):
        requested = scope_set(scopes)
        candidates = [r for r in self.rules.values() if r["rule_group"] == group
                      and active(r, as_of) and requested & scope_set(r["scope"])]
        result = []
        for rule in candidates:
            # Keep partially superseded rules: comparison is evaluated per leaf scope.
            remaining = requested & scope_set(rule["scope"])
            for other in candidates:
                remaining = {s for s in remaining if not self.supersedes(
                    other["rule_id"], rule["rule_id"], as_of, {s})}
            if remaining:
                result.append(rule)
        return result

    def relation(self, a, b, as_of, scopes):
        overlap = scope_set(a["scope"]) & scope_set(b["scope"]) & scope_set(scopes)
        if (a["rule_group"] != b["rule_group"] or not overlap or not interval_overlap(a, b)
                or not active(a, as_of) or not active(b, as_of)):
            return "unrelated"
        unresolved = {s for s in overlap if not (
            self.supersedes(a["rule_id"], b["rule_id"], as_of, {s}) or
            self.supersedes(b["rule_id"], a["rule_id"], as_of, {s}))}
        if not unresolved:
            return "overridden"
        if any(a[k] != b[k] for k in ("unit", "period", "reference_event", "conditions")):
            return "uncertain"
        if self.groups[a["rule_group"]]["semantics"] == "functional":
            return "consistent" if (a["constraint_type"], a["value"]) == (b["constraint_type"], b["value"]) else "conflict"
        def bounds(r):
            v, op = r["value"], r["operator"]
            return (v, v) if op == "=" else ((v, float("inf")) if op == ">=" else (0, v))
        if isinstance(a["value"], str) or isinstance(b["value"], str):
            return "uncertain"
        lo1, hi1 = bounds(a)
        lo2, hi2 = bounds(b)
        return "conflict" if max(lo1, lo2) > min(hi1, hi2) else "consistent"
