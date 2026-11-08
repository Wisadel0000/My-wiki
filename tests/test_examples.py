"""示例 wiki 的回归测试：它同时是文档，必须始终合法且互链完整。"""

from __future__ import annotations

from pathlib import Path

from wikiencoder.index import WikiIndex
from wikiencoder.store import WikiStore
from wikiencoder.validate import validate_store

EXAMPLES = Path("examples")


def test_examples_are_valid() -> None:
    store = WikiStore(EXAMPLES)
    report = validate_store(store)
    assert report.ok, str(report)
    assert report.errors == []


def test_examples_are_interlinked() -> None:
    store = WikiStore(EXAMPLES)
    index = WikiIndex(store)
    assert len(index) == 4
    assert index.broken_links() == []
    assert index.broken_anchors() == []
    assert index.backlink_pairs("傅里叶变换")
    entry = index.get("傅里叶变换")
    assert entry is not None
    assert "积分变换" in entry.parents
    assert "卷积定理" in entry.related


def test_examples_config_is_picked_up() -> None:
    store = WikiStore(EXAMPLES)
    assert store.author == "我"
    assert store.pages_dir.name == "pages"


def test_examples_roundtrip_lossless() -> None:
    from wikiencoder import parse, serialize

    for path in sorted((EXAMPLES / "pages").glob("*.wiki")):
        text = path.read_bytes().decode("utf-8")
        assert serialize(parse(text)) == text, f"{path.name} round-trip 失败"
