"""Whitelisted data tools; fault injection does not choose recovery actions."""
import copy

from .retriever import Retriever


def error(kind, message, retryable=False, **details):
    return {"ok": False, "error_type": kind, "message": message,
            "retryable": retryable, **details}


class Tools:
    def __init__(self, corpus, fault=None):
        if fault not in (None, "search_docs:once", "search_docs:always"):
            raise ValueError("未知故障注入配置")
        self.corpus = corpus
        self.retriever = Retriever(corpus)
        self.fault = fault
        self.search_count = 0
        self.successful_searches = 0
        self.failures = 0
        self.read = {}

    def execute(self, name, args):
        if name == "search_docs":
            self.search_count += 1
            if self.fault == "search_docs:always" or (
                    self.fault == "search_docs:once" and self.search_count == 1):
                self.failures += 1
                return error("INJECTED_FAILURE", "检索工具故障（测试注入）", True)
            self.successful_searches += 1
            return {"ok": True, "results": self.retriever.search(args["query"], args.get("top_k", 5))}
        if name == "read_doc":
            doc = self.corpus.documents.get(args["doc_id"])
            if doc is None:
                return error("NOT_FOUND", "文档 ID 不存在")
            self.read[doc["doc_id"]] = copy.deepcopy(doc)
            return {"ok": True, **copy.deepcopy(doc)}
        return error("UNKNOWN_TOOL", "不支持的工具")
