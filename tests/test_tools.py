from src.tools import Tools


def test_read_and_unknown(corpus):
    tools = Tools(corpus)
    assert tools.execute("read_doc", {"doc_id": "invalid"})["error_type"] == "NOT_FOUND"
    result = tools.execute("read_doc", {"doc_id": "D03"})
    assert result["content"] == corpus.documents["D03"]["content"]
    assert "D03" in tools.read
    result["content"] = "changed"
    assert tools.read["D03"]["content"] != "changed"


def test_discovery_is_not_read(corpus):
    tools = Tools(corpus)
    assert tools.execute("search_docs", {"query": "远程办公"})["results"]
    assert tools.read == {}


def test_once_and_always(corpus):
    once, always = Tools(corpus, "search_docs:once"), Tools(corpus, "search_docs:always")
    for tool in (once, always):
        assert tool.execute("search_docs", {"query": "远程办公"}) == {
            "ok": False, "error_type": "INJECTED_FAILURE", "message": "检索工具故障（测试注入）", "retryable": True}
    assert once.execute("search_docs", {"query": "远程办公"})["ok"]
    assert not always.execute("search_docs", {"query": "远程办公"})["ok"]
