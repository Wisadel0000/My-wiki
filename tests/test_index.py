"""索引与校验测试。"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest

from wikiencoder import syntax as S
from wikiencoder.index import WikiIndex, normalize_key
from wikiencoder.model import Section
from wikiencoder.store import WikiStore
from wikiencoder.validate import lint_page, validate_store


@pytest.fixture()
def store() -> Iterator[WikiStore]:
    root = Path(".pytest-tmp") / f"idx-{uuid4().hex[:8]}"
    root.mkdir(parents=True)
    store = WikiStore(root, author="我")
    try:
        yield store
    finally:
        shutil.rmtree(root, ignore_errors=True)


def write(store: WikiStore, slug: str, text: str) -> None:
    store.pages_dir.mkdir(parents=True, exist_ok=True)
    store.path_for(slug).write_text(text, encoding="utf-8")


@pytest.fixture()
def wiki(store: WikiStore) -> WikiStore:
    store.create("积分变换", kind="概念", body="更一般的形式。\n")
    store.create("傅里叶变换", kind="概念", tags=["变换"], body="## 定义\n把时域映射到频域。\n")
    store.update(
        "傅里叶变换",
        lambda ed: (
            ed.add_alias("Fourier transform"),
            ed.set_infobox("父级", "[[积分变换]]"),
            ed.set_infobox("领域", "数学 / 分析"),
            ed.add_seealso("积分变换", note="更一般的形式"),
            ed.append_preamble("傅里叶变换把信号拆成复指数之和，见 [[积分变换]]。"),
        ),
    )
    store.create("卷积定理", kind="定理", body="$$F(f*g)=F(f)F(g)$$\n")
    return store


def test_resolve_by_slug_title_and_alias(wiki: WikiStore) -> None:
    index = WikiIndex(wiki)
    assert index.resolve("傅里叶变换") == "傅里叶变换"
    assert index.resolve("Fourier transform") == "傅里叶变换"
    assert index.resolve("fourier  TRANSFORM") == "傅里叶变换"
    assert index.resolve("不存在的页") is None


def test_normalize_key() -> None:
    assert normalize_key(" Fourier  Transform ") == "fourier-transform"
    assert normalize_key("傅里叶_变换") == "傅里叶-变换"


def test_backlinks(wiki: WikiStore) -> None:
    index = WikiIndex(wiki)
    assert index.backlinks("积分变换") == ["傅里叶变换"]
    pairs = index.backlink_pairs("积分变换")
    assert pairs == [("傅里叶变换", "傅里叶变换")]


def test_edge_kinds(wiki: WikiStore) -> None:
    index = WikiIndex(wiki)
    kinds = {(source, target, kind) for source, target, kind in index.edges}
    assert ("傅里叶变换", "积分变换", "parent") in kinds
    assert ("傅里叶变换", "积分变换", "seealso") in kinds
    assert ("傅里叶变换", "积分变换", "mention") in kinds


def test_broken_links_and_orphans(store: WikiStore) -> None:
    write(store, "甲", "@ 序言\n见 [[幽灵页]]。\n")
    index = WikiIndex(store)
    broken = index.broken_links()
    assert [(slug, link.target) for slug, link in broken] == [("甲", "幽灵页")]
    # 唯一的出链是红链 → 在图谱上等于没有连接，算孤岛
    assert index.orphans() == ["甲"]


def test_broken_anchors(store: WikiStore) -> None:
    write(store, "甲", "@ 详细内容\n## 定义\n内容。\n")
    write(store, "乙", "@ 序言\n见 [[甲#定义]] 与 [[甲#没有这个锚点]]。\n")
    index = WikiIndex(store)
    anchors = index.broken_anchors()
    assert len(anchors) == 1
    assert anchors[0][1].anchor == "没有这个锚点"


def test_resolver_marks_broken(wiki: WikiStore) -> None:
    index = WikiIndex(wiki)
    assert index.resolver("傅里叶变换") == ("傅里叶变换.html", False)
    href, broken = index.resolver("幽灵页", "锚点")
    assert broken is True
    assert href == "幽灵页.html"


def test_search(wiki: WikiStore) -> None:
    index = WikiIndex(wiki)
    assert [entry.slug for entry in index.search("卷积")] == ["卷积定理"]
    assert index.search("变换")[0].slug in {"傅里叶变换", "积分变换"}
    assert index.search("") == []


def test_tags_and_graph(wiki: WikiStore) -> None:
    index = WikiIndex(wiki)
    assert index.tags() == {"变换": ["傅里叶变换"]}
    graph = index.graph()
    assert len(graph["nodes"]) == 3
    assert any(edge["kind"] == "parent" for edge in graph["edges"])


def test_index_json_can_be_written_and_reloaded(wiki: WikiStore) -> None:
    index = WikiIndex(wiki)
    path = index.save()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data["pages"]) == {"傅里叶变换", "积分变换", "卷积定理"}
    entry = data["pages"]["傅里叶变换"]
    assert entry["title"] == "傅里叶变换"
    assert entry["tags"] == ["变换"]
    assert entry["parents"] == ["积分变换"]
    assert "傅里叶变换把信号" in entry["excerpt"]


def test_validate_reports_broken_link_with_line(store: WikiStore) -> None:
    write(store, "甲", "---\ntitle: 甲\n---\n\n@ 序言\n见 [[幽灵页]]。\n")
    report = validate_store(store)
    broken = [item for item in report.items if item.code == "E401"]
    assert len(broken) == 1
    assert broken[0].line == 6
    assert report.ok is True  # 红链只是警告


def test_validate_missing_title_is_error(store: WikiStore) -> None:
    write(store, "无题", "---\nformat: 1\n---\n\n@ 序言\n内容。\n")
    report = validate_store(store)
    assert not report.ok
    assert any(item.code == "E102" and item.level == "error" for item in report.items)


def test_validate_duplicate_titles(store: WikiStore) -> None:
    write(store, "a", "---\ntitle: 同名\n---\n\n@ 序言\n甲。\n")
    write(store, "b", "---\ntitle: 同名\n---\n\n@ 序言\n乙。\n")
    report = validate_store(store)
    assert any(item.code == "E506" for item in report.items)


def test_validate_self_link_and_orphan(store: WikiStore) -> None:
    write(store, "甲", "---\ntitle: 甲\n---\n\n@ 序言\n见 [[甲]]。\n")
    write(store, "乙", "---\ntitle: 乙\n---\n\n@ 序言\n没人理我。\n")
    report = validate_store(store)
    assert any(item.code == "E602" for item in report.items)
    assert any(item.code == "E601" and "乙" in item.message for item in report.items)


def test_validate_clean_wiki_passes(wiki: WikiStore) -> None:
    report = validate_store(wiki)
    assert report.ok
    assert report.errors == []
    text = str(report)
    assert isinstance(text, str) and text


def test_kinds_grouping(wiki: WikiStore) -> None:
    index = WikiIndex(wiki)
    kinds = index.kinds()
    assert set(kinds) == {"概念", "定理"}
    assert set(kinds["概念"]) == {"傅里叶变换", "积分变换"}
    assert kinds["定理"] == ["卷积定理"]
    assert set(index.by_kind("概念")) == {"傅里叶变换", "积分变换"}
    assert index.by_kind("不存在的类型") == []


def test_kinds_puts_unclassified_last(store: WikiStore) -> None:
    write(store, "有类型", "---\ntitle: 甲\ntype: 概念\n---\n\n@ 序言\nx\n")
    write(store, "没类型", "---\ntitle: 乙\n---\n\n@ 序言\ny\n")
    kinds = WikiIndex(store).kinds()
    assert set(kinds) == {"概念", "（未分类）"}
    assert kinds["（未分类）"] == ["没类型"]


def test_create_warns_when_extra_collides_with_canonical(store: WikiStore) -> None:
    """自定义板块撞规范名：create 给警告，落盘后会被解析成重复板块。"""
    result = store.create("甲", extra={"标识信息框": "父级: [[乙]]\n"})
    assert result.ok
    assert any("规范板块" in warning for warning in result.warnings)

    page = store.load("甲")
    assert page.section_keys().count("infobox") == 2
    assert page.infobox_fields() == []  # 读到的是骨架里那个空的信息框

    report = validate_store(store)
    assert any(item.code == "E504" for item in report.items)


def test_lint_flags_extra_collision_and_duplicate_titles(store: WikiStore) -> None:
    store.create("甲")
    page = store.load("甲")
    page.sections.append(Section(key=S.EXTRA, title="参见", body="- [[甲]]\n", line=0))
    page.sections.append(Section(key=S.EXTRA, title="附录", body="a\n", line=0))
    page.sections.append(Section(key=S.EXTRA, title="附录", body="b\n", line=0))

    report = lint_page(page, WikiIndex(store), slug="甲")
    codes = [item.code for item in report.items]
    assert "E508" in codes
    assert "E509" in codes
