"""函数式编辑 API 测试（wikiencoder.ops + WikiStore.modify）。"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from functools import partial
from pathlib import Path
from uuid import uuid4

import pytest

from wikiencoder import ops, parse
from wikiencoder.store import WikiStore


@pytest.fixture()
def store() -> Iterator[WikiStore]:
    root = Path(".pytest-tmp") / f"ops-{uuid4().hex[:8]}"
    root.mkdir(parents=True)
    store = WikiStore(root, author="我")
    try:
        yield store
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_free_functions_mutate_page_in_place() -> None:
    page = parse("@ 序言\n开场。\n\n@ 标识信息框\n领域: 数学\n")
    assert ops.set_infobox(page, "父级", "[[积分变换]]") is True
    assert ops.add_tag(page, "信号处理") is True
    assert ops.add_seealso(page, "积分变换", note="更一般的形式") is True
    assert ops.set_section(page, "详细内容", "## 定义\n内容。\n") is True

    text = page.to_text()
    assert "父级: [[积分变换]]" in text
    assert "tags: 信号处理" in text
    assert "- [[积分变换]] —— 更一般的形式" in text
    assert "## 定义" in text


def test_free_functions_are_idempotent() -> None:
    page = parse("@ 序言\n开场。\n")
    assert ops.add_tag(page, "数学") is True
    assert ops.add_tag(page, "数学") is False
    assert ops.set_infobox(page, "领域", "数学") is True
    assert ops.set_infobox(page, "领域", "数学") is False


def test_apply_composes_with_partial() -> None:
    page = parse("@ 序言\nx\n")
    changed = ops.apply(
        page,
        partial(ops.add_tag, tag="数学"),
        partial(ops.set_infobox, key="领域", value="分析"),
        partial(ops.add_edit_record, message="补充"),
    )
    assert changed is True
    assert page.tags == ["数学"]
    assert page.infobox_dict() == {"领域": "分析"}
    assert page.edit_records()[0].message == "补充"

    assert ops.apply(page, partial(ops.add_tag, tag="数学")) is False


def test_add_edit_record_sets_author_and_date() -> None:
    page = parse("@ 序言\nx\n")
    ops.add_edit_record(page, "创建", date="2024-05-01", author="我")
    record = page.edit_records()[0]
    assert (record.date, record.author, record.message) == ("2024-05-01", "我", "创建")


def test_store_modify_writes_and_is_idempotent(store: WikiStore) -> None:
    store.create("甲", body="## 节\n内容。\n")
    result = store.modify(
        "甲",
        lambda page: ops.apply(
            page,
            partial(ops.add_tag, tag="新标签"),
            partial(ops.set_infobox, key="领域", value="数学"),
        ),
    )
    assert result.ok and result.changed
    assert "+tags: 新标签" in result.diff

    reloaded = store.load("甲")
    assert reloaded.tags == ["新标签"]
    assert reloaded.infobox_dict() == {"领域": "数学"}

    again = store.modify("甲", lambda page: ops.add_tag(page, "新标签"))
    assert again.changed is False


def test_store_modify_supports_dry_run(store: WikiStore) -> None:
    store.create("甲")
    before = store.path_for("甲").read_bytes()
    result = store.modify("甲", lambda page: ops.add_tag(page, "干跑"), dry_run=True)
    assert result.changed and "干跑" in result.diff
    assert store.path_for("甲").read_bytes() == before


def test_ops_only_mutate_memory_until_saved(store: WikiStore) -> None:
    """ops / Editor 只改内存对象；不显式 save 就绝不碰文件。"""
    store.create("甲")
    path = store.path_for("甲")
    before = path.read_bytes()

    page = store.load("甲")
    assert ops.add_tag(page, "只在内存") is True
    assert ops.set_infobox(page, "领域", "数学") is True

    assert path.read_bytes() == before, "没有 save 之前，磁盘必须一个字节都不变"
    assert page.tags == ["只在内存"], "内存里的对象已经变了"

    store.save(page)
    assert path.read_bytes() != before
    assert store.load("甲").tags == ["只在内存"]


def test_unsaved_mutation_is_invisible_to_fresh_load(store: WikiStore) -> None:
    """store.load 每次返回干净副本：改了不存，下一次 load 看不到。"""
    store.create("甲")
    page = store.load("甲")
    ops.add_tag(page, "丢弃")
    assert page.tags == ["丢弃"]
    assert store.load("甲").tags == []
