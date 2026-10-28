"""Lossless semantic canonicalization. Never selects tools or changes rule values."""
import copy

PERIODS = {
    "每周": "每周", "一周": "每周", "周": "每周", "week": "每周", "weekly": "每周", "per week": "每周", "1 week": "每周",
    "每月": "每月", "一月": "每月", "月": "每月", "month": "每月", "monthly": "每月", "per month": "每月",
    "每年": "每年", "一年": "每年", "年": "每年", "year": "每年", "yearly": "每年", "annually": "每年",
}
SCOPE_ALIASES = {"regular": "regular", "正式员工": "regular", "正式职工": "regular",
                 "probation": "probation", "试用期": "probation", "试用期员工": "probation",
                 "all_employees": "all_employees", "全体员工": "all_employees", "所有员工": "all_employees"}
EVENTS = {"出差结束后": "差旅结束后", "差旅结束后": "差旅结束后",
          "出差结束前": "差旅结束前", "差旅结束前": "差旅结束前"}
CONDITIONS = {"主管审批": "主管审批", "主管批准": "主管审批", "manager_approval": "主管审批",
              "有效票据": "有效票据", "通过内部系统": "通过内部系统", "提前提交审批": "提前提交审批",
              "不自动适用正式员工的固定额度": "不自动适用正式员工的固定额度", "禁止公开分享": "禁止公开分享"}


def issue(code, field, actual, expected, corrections, source="model"):
    return {"error_type": code, "field": field, "actual": copy.deepcopy(actual),
            "expected_semantics": expected, "allowed_corrections": corrections, "constraint_source": source}


def token(value):
    return value.strip().lower() if isinstance(value, str) else value


def normalize_contract(contract):
    return normalize_arguments({"question_contract": contract})


def normalize_arguments(arguments):
    """Return a copy, transformation log, and semantic errors before Schema checks.

    Structural errors are left to JSON Schema. Unknown values are never guessed.
    Raw caller arguments remain independently recorded by the executor.
    """
    result, changes, errors = copy.deepcopy(arguments), [], []
    if not isinstance(result, dict):
        return result, changes, errors
    containers = []
    contract = result.get("question_contract")
    if isinstance(contract, dict) and isinstance(contract.get("requirements"), list):
        containers.extend((f"question_contract.requirements.{i}", r) for i, r in enumerate(contract["requirements"]))
    if isinstance(result.get("claims"), list):
        containers.extend((f"claims.{i}", c) for i, c in enumerate(result["claims"]))
    for path, item in containers:
        if not isinstance(item, dict):
            continue
        original = copy.deepcopy(item)
        scopes = item.get("scope")
        if isinstance(scopes, list) and all(isinstance(s, str) for s in scopes):
            scopes = sorted({SCOPE_ALIASES.get(token(s), s) for s in scopes})
            if "all_employees" in scopes or set(scopes) == {"regular", "probation"}:
                scopes = ["all_employees"]
            item["scope"] = scopes
        period = item.get("period")
        if isinstance(period, str):
            canonical = PERIODS.get(token(period))
            if canonical is None:
                errors.append(issue("UNKNOWN_PERIOD", path + ".period", period,
                                    "日历周期：每周/每月/每年或null；数字7不等于日历周",
                                    ["使用每周、每月、每年；非周期问题用null", "不得将每月改成每周来满足证据"]))
            else:
                item["period"] = canonical
        event = item.get("reference_event")
        if isinstance(event, str):
            event_period = PERIODS.get(token(event))
            if event_period:
                if item.get("period") in (None, event_period) and item.get("constraint_type") != "DEADLINE":
                    item["period"], item["reference_event"] = event_period, None
                else:
                    errors.append(issue("EVENT_PERIOD_CONFLICT", path + ".reference_event", event,
                                        "周期不能充当截止起算事件；DEADLINE需要真实事件",
                                        ["保留正确period，修正模型推断的reference_event；有用户依据的事件不得删除"]))
            else:
                item["reference_event"] = EVENTS.get(token(event), event.strip())
        conditions = item.get("conditions")
        if isinstance(conditions, list) and all(isinstance(c, str) for c in conditions):
            remaining = []
            for condition in conditions:
                label = SCOPE_ALIASES.get(token(condition))
                if label:
                    from .rules import scope_set
                    if isinstance(scopes, list) and scope_set([label]) <= scope_set(scopes):
                        continue  # Redundant employee class is already retained in scope.
                    errors.append(issue("SCOPE_CONDITION_CONFLICT", path + ".conditions", condition,
                                        "员工类别只属于scope，且不能与scope冲突",
                                        ["修正员工类型解释，同时保留用户明确的scope"]))
                    remaining.append(condition)
                else:
                    remaining.append(CONDITIONS.get(token(condition), condition.strip()))
            item["conditions"] = sorted(set(remaining))
        for field in ("scope", "period", "reference_event", "conditions"):
            if original.get(field) != item.get(field):
                changes.append({"field": path + "." + field, "before": original.get(field),
                                "after": copy.deepcopy(item.get(field)), "reason": "合法同义值或字段归属规范化"})
    return result, changes, errors
