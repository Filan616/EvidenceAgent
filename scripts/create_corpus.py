"""Rebuild only synthetic fixture data. Not a runtime answer generator."""
import json
from pathlib import Path

from src.rules import render_rule


def build():
    specs = [
        ("D01", "差旅报销制度 A", "travel_reimbursement", "all_employees", "DEADLINE", 30, "days", "差旅结束后", None, []),
        ("D02", "差旅报销制度 B", "travel_reimbursement", "all_employees", "DEADLINE", 15, "days", "差旅结束后", None, []),
        ("D03", "正式员工远程办公", "remote_work", "regular", "MAX", 2, "days", None, "每周", []),
        ("D04", "试用期远程办公", "remote_work", "probation", "EXACT", "试用期员工申请远程办公需主管审批，不自动适用正式员工的固定额度。", "text", None, None, ["主管审批", "不自动适用正式员工的固定额度"]),
        ("D05", "年假申请", "annual_leave", "all_employees", "EXACT", "员工申请年假需通过内部系统提前提交审批。", "text", None, None, ["通过内部系统", "提前提交审批"]),
        ("D06", "报销票据要求", "reimbursement_receipts", "all_employees", "EXACT", "员工办理差旅报销需提交有效票据。", "text", None, None, ["有效票据"]),
        ("D07", "信息安全 FAQ", "information_security", "all_employees", "EXACT", "员工禁止公开分享内部账号和凭证。", "text", None, None, ["禁止公开分享"]),
    ]
    docs = []
    for index, (did, title, group, scope, kind, value, unit, event, period, conditions) in enumerate(specs):
        rule = {"rule_id": did + "-R1", "rule_group": group, "scope": [scope],
                "effective_from": "2026-01-01", "effective_to": None,
                "operator": {"MAX": "<=", "DEADLINE": "<=", "EXACT": "="}[kind],
                "constraint_type": kind, "value": value, "unit": unit,
                "reference_event": event, "period": period, "conditions": conditions,
                "supersedes": [], "evidence": "",
                "facets": (["limit"] if did in {"D01", "D02", "D03"} else
                           (["procedure", "requirements", "limit"] if did == "D04" else
                            (["procedure", "requirements"] if did == "D05" else ["requirements"])))}
        rule["evidence"] = render_rule(rule)
        docs.append({"doc_id": did, "title": title, "version_date": f"2026-0{min(index + 1, 7)}-01",
                     "scope": [scope], "content": rule["evidence"] + "本资料为合成制度，仅用于项目测试。",
                     "rules": [rule]})
    groups = {group: {"semantics": "functional", "description": title}
              for _, title, group, *_ in specs}
    groups["travel_reimbursement"]["description"] = "差旅报销唯一规定期限；不是多个独立可叠加上限"
    groups["remote_work"]["description"] = "按员工类型规定的远程办公额度或申请规则"
    return {"rule_groups": groups, "documents": docs}


if __name__ == "__main__":
    destination = Path("data/documents.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
