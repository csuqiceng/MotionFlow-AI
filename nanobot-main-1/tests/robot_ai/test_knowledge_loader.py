from __future__ import annotations

from robot_ai.knowledge.loader import KnowledgeStore
from robot_ai.knowledge.models import KnowledgeEntry


def test_entry_round_trip() -> None:
    e = KnowledgeEntry(
        category="safety",
        title="E-stop",
        content="Press red button",
        source="assistant_knowledge_base.json",
    )
    d = e.to_dict()
    assert d["category"] == "safety"
    assert KnowledgeEntry.from_dict(d).title == "E-stop"


def test_store_load_and_query(tmp_path) -> None:
    p = tmp_path / "k.json"
    store = KnowledgeStore(p)
    store.replace(
        [
            KnowledgeEntry(category="safety", title="A", content="ca", source="t"),
            KnowledgeEntry(category="error_code", title="B", content="cb", source="t"),
        ]
    )
    loaded = KnowledgeStore(p).load()
    assert len(loaded) == 2
    assert KnowledgeStore(p).query(category="safety")[0].title == "A"
    assert KnowledgeStore(p).query(keyword="cb")[0].category == "error_code"
