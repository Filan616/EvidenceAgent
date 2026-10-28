import pytest

from src.retriever import Retriever


@pytest.mark.parametrize("query,expected", [
    ("正式员工远程办公", "D03"), ("差旅报销期限", "D01"),
    ("年假申请", "D05"), ("试用期远程办公", "D04")])
def test_positive(corpus, query, expected):
    assert expected in {r["doc_id"] for r in Retriever(corpus).search(query)}


@pytest.mark.parametrize("query", ["公司今年利润是多少", "宇宙飞船发动机", "xyzzy qqqqq"])
def test_irrelevant_is_empty(corpus, query):
    assert Retriever(corpus).search(query) == []


def test_conflicting_candidates_and_determinism(corpus):
    retriever = Retriever(corpus)
    first = retriever.search("差旅报销期限")
    assert {"D01", "D02"} <= {r["doc_id"] for r in first}
    assert first == retriever.search("差旅报销期限")
    assert len(retriever.search("差旅报销期限", 1)) == 1


@pytest.mark.parametrize("k", [0, 11, True, 1.5])
def test_top_k(corpus, k):
    with pytest.raises(ValueError):
        Retriever(corpus).search("远程办公", k)
