"""Explicit scripted decisions. These fixtures never represent live intelligence."""
import copy

from src.evidence_validator import claim_for
from src.llm_client import assistant, call

AS_OF = "2026-10-28"


def contract(group="remote_work", scope="regular", period="每周", ambiguous=False):
    return {"requirements": [{"rule_group": group, "scope": [scope], "as_of": AS_OF,
             "reference_event": "差旅结束后" if group == "travel_reimbursement" else None,
             "period": period, "conditions": [], "facet": "all",
             "constraint_type": ("DEADLINE" if group == "travel_reimbursement" else
                                 ("MAX" if group == "remote_work" and scope == "regular" else None))}],
             "ambiguous": ambiguous, "clarification": "需确认适用范围" if ambiguous else "", "revision_reason": ""}


def args(**kwargs):
    return {"reason": "离线测试动作说明", "question_contract": None, **kwargs}


def submission(corpus, ids=("D03-R1",), status="COMPLETED"):
    claims = [copy.deepcopy(claim_for(corpus.rules[rid], corpus.rule_docs[rid])) for rid in ids]
    citations = []
    for c in claims:
        citation = {"doc_id": c["evidence_doc_id"], "quote": c["evidence_quote"]}
        if citation not in citations:
            citations.append(citation)
    return args(status=status, answer="此自由文本不得直接作为最终答案。", claims=claims,
                citations=citations, gaps=[] if status == "COMPLETED" else ["缺少适用依据"],
                conflicts=["存在冲突"] if status == "NEEDS_CLARIFICATION" and len(ids) > 1 else [])


def normal_script(corpus):
    return [
        assistant(call("search_docs", args(query="正式员工远程办公", top_k=5, question_contract=contract()), "n1")),
        assistant(call("read_doc", args(doc_id="D03"), "n2")),
        assistant(call("submit_answer", submission(corpus), "n3")),
    ]


def conflict_script(corpus):
    c = contract("travel_reimbursement", "all_employees", None)
    return [assistant(call("search_docs", args(query="差旅报销期限", top_k=5, question_contract=c), "c1")),
            assistant(call("read_doc", args(doc_id="D01"), "c2")),
            assistant(call("read_doc", args(doc_id="D02"), "c3")),
            assistant(call("submit_answer", submission(corpus, ("D01-R1", "D02-R1"), "NEEDS_CLARIFICATION"), "c4"))]


def missing_script(corpus):
    return [assistant(call("search_docs", args(query="公司今年利润", top_k=5,
                         question_contract=contract("unknown", "all_employees", None)), "m1")),
            assistant(call("submit_answer", submission(corpus, (), "INSUFFICIENT_EVIDENCE"), "m2"))]
