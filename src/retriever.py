"""Deterministic sparse retrieval; relevance is not evidence."""
import math
import re
from collections import Counter


def tokenize(text):
    tokens = re.findall(r"[a-z0-9_]+", text.lower())
    for span in re.findall(r"[\u4e00-\u9fff]+", text):
        for size in (2, 3):
            tokens.extend(span[i:i + size] for i in range(len(span) - size + 1))
    return tokens


class Retriever:
    def __init__(self, corpus, threshold=0.08):
        if not 0 < threshold <= 1:
            raise ValueError("相似度阈值应在 (0,1] 内")
        self.documents = corpus.documents
        self.threshold = threshold
        counts = {key: Counter(tokenize(doc["title"] + " " + doc["content"]))
                  for key, doc in self.documents.items()}
        df = Counter(term for counts_ in counts.values() for term in counts_)
        self.idf = {term: math.log((1 + len(counts)) / (1 + count)) + 1
                    for term, count in df.items()}
        self.vectors = {key: self._vector(count) for key, count in counts.items()}

    def _vector(self, counts):
        vector = {term: (1 + math.log(count)) * self.idf.get(term, 1)
                  for term, count in counts.items()}
        norm = math.sqrt(sum(value ** 2 for value in vector.values())) or 1
        return {term: value / norm for term, value in vector.items()}

    def search(self, query, top_k=5):
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 10:
            raise ValueError("top_k 必须为 1—10 的整数")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query 不能为空")
        vector = self._vector(Counter(tokenize(query)))
        results = []
        for key, candidate in self.vectors.items():
            score = sum(value * candidate.get(term, 0) for term, value in vector.items())
            if score >= self.threshold:
                doc = self.documents[key]
                results.append({"doc_id": key, "title": doc["title"],
                                "version_date": doc["version_date"], "score": round(score, 6),
                                "snippet": doc["content"][:140]})
        return sorted(results, key=lambda item: (-item["score"], item["doc_id"]))[:top_k]
