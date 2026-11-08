"""store / editor 测试：原子写、幂等、dry-run、结构化编辑、重命名。"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest

from wikiencoder import parse
from wikiencoder.store import WikiStore, slugify_title


@pytest.fixture()
def root() -> Iterator[Path]:
    path = Path(".pytest-tmp") / f"wiki-{uuid4().hex[:8]}"
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture()
def store(root: Path) -> WikiStore:
    return WikiStore(root, author="我")


def test_create_and_load(store: WikiStore) -> None:
    result = store.create("傅里叶变换", kind="概念", tags=["变换"])
    assert result.ok and result.changed
    assert store.path_for("傅里叶变换").is_file()

    page = store.load("傅里叶变换")
    assert page.slug == "傅里叶变换"
    assert page.title == "傅里叶变换"
    assert page.kind == "概念"
    assert page.tags == ["变换"]
    assert page.section_keys() == ["preamble", "infobox", "body"]


def test_create_refuses_overwrite(store: WikiStore) -> None:
    store.create("甲")
    again = store.create("甲")
    assert not again.ok
    assert "页面已存在" in again.errors[0]


def test_save_is_idempotent(store: WikiStore) -> None:
    store.create("甲", body="内容\n")
    page = store.load("甲")
    result = store.save(page)
    assert result.changed is False
    assert result.diff == ""


def test_dry_run_returns_diff_but_does_not_write(store: WikiStore) -> None:
    store.create("甲", body="旧内容\n")
    before = store.text_for("甲")
    result = store.update("甲", lambda ed: ed.append_section("详细内容", "新内容"), dry_run=True)
    assert result.changed
    assert "+新内容" in result.diff
    assert store.text_for("甲") == before


def test_editor_writes_structured_sections(store: WikiStore) -> None:
    store.create("甲")
    store.update(
        "甲",
        lambda ed: (
            ed.set_infobox("领域", "数学"),
            ed.set_infobox("父级", "[[乙]]"),
            ed.add_tag("信号处理"),
            ed.add_seealso("乙", note="更一般的形式"),
            ed.add_source("书", "《信号与系统》"),
        ),
    )
    page = store.load("甲")
    assert page.infobox_dict() == {"领域": "数学", "父级": "[[乙]]"}
    assert page.tags == ["信号处理"]
    items = page.seealso_items()
    assert [(item.target, item.note) for item in items] == [("乙", "更一般的形式")]
    assert page.source_items()[0].kind == "书"


def test_edit_records_are_only_added_manually(store: WikiStore) -> None:
    store.create("甲")
    store.update("甲", lambda ed: ed.append_section("详细内容", "正文\n"))
    assert store.load("甲").edit_records() == [], "普通编辑不应该产生日志"

    store.update("甲", lambda ed: ed.add_edit_record("补充正文"))
    records = store.load("甲").edit_records()
    assert len(records) == 1
    assert records[0].message == "补充正文"
    assert records[0].author == "我"  # 来自 store.author

    store.update("甲", lambda ed: ed.add_edit_record("再补一句"))
    records = store.load("甲").edit_records()
    assert [record.n for record in records] == [1, 2]

    store.update("甲", lambda ed: ed.remove_edit_record(1))
    records = store.load("甲").edit_records()
    assert [record.message for record in records] == ["再补一句"]
    assert records[0].n == 1  # 编号自动重排


def test_edit_record_can_be_amended(store: WikiStore) -> None:
    store.create("甲")
    store.update("甲", lambda ed: ed.add_edit_record("草稿"))
    store.update("甲", lambda ed: ed.amend_edit_record(1, message="定稿", date="2024-01-02"))
    record = store.load("甲").edit_records()[0]
    assert (record.message, record.date) == ("定稿", "2024-01-02")


def test_editing_leaves_other_bytes_untouched(store: WikiStore) -> None:
    store.create("甲", body="## 小节\n原有内容。\n", preamble="开场白。\n")
    before = store.text_for("甲").splitlines(keepends=True)
    store.update("甲", lambda ed: ed.add_tag("新标签"))
    after = store.text_for("甲").splitlines(keepends=True)
    changed = [line for line in after if line not in before]
    assert len(changed) == 1
    assert changed[0].startswith("tags:")


def test_atomic_write_leaves_no_temp_files(store: WikiStore) -> None:
    store.create("甲", body="内容\n")
    store.update("甲", lambda ed: ed.append_section("详细内容", "更多\n"))
    leftovers = [path.name for path in store.pages_dir.iterdir() if path.suffix == ".tmp"]
    assert leftovers == []


def test_rename_updates_backlinks_and_keeps_alias(root: Path) -> None:
    store = WikiStore(root)
    store.create("甲", body="见[[]]\n")
    store.create("乙", body="指向 [[甲]] 的引用。\n")
    store.create("丙", body="也见 [[甲|甲页]]。\n")

    result = store.rename("甲", "甲新")
    assert result.ok and result.changed
    assert not store.path_for("甲").exists()
    assert store.path_for("甲新").is_file()
    assert "[[甲新]]" in store.text_for("乙")
    assert "[[甲新|甲页]]" in store.text_for("丙")
    assert "甲" in store.load("甲新").aliases


def test_rename_refuses_existing_target(store: WikiStore) -> None:
    store.create("甲")
    store.create("乙")
    result = store.rename("甲", "乙")
    assert not result.ok
    assert "目标已存在" in result.errors[0]


def test_rename_dry_run_changes_nothing(store: WikiStore) -> None:
    store.create("甲")
    store.create("乙", body="[[甲]]\n")
    before = store.text_for("乙")
    result = store.rename("甲", "甲2", dry_run=True)
    assert result.changed
    assert store.text_for("乙") == before
    assert store.path_for("甲").is_file()


def test_delete_moves_to_trash(store: WikiStore) -> None:
    store.create("待删")
    result = store.delete("待删")
    assert result.ok and result.changed
    assert not store.path_for("待删").exists()
    assert (store.root / ".trash" / "待删.wiki").is_file()


def test_transaction_commits_all_pages(store: WikiStore) -> None:
    store.create("甲")
    store.create("乙")
    with store.transaction() as tx:
        tx.edit("甲", lambda ed: ed.add_tag("共同"))
        tx.edit("乙", lambda ed: ed.add_tag("共同"))
    assert store.load("甲").tags == ["共同"]
    assert store.load("乙").tags == ["共同"]


def test_slugify_title_handles_windows_rules() -> None:
    assert slugify_title("傅里叶变换") == "傅里叶变换"
    assert slugify_title('a/b:c*d?"e<f>g|h') == "abcdefgh"
    assert slugify_title("傅里叶 变换") == "傅里叶-变换"
    assert slugify_title("con") == "_con"
    assert slugify_title("   ") == "untitled"


def test_load_reports_slug_mismatch(store: WikiStore) -> None:
    store.create("甲")
    path = store.path_for("甲")
    path.write_text(
        parse(store.text_for("甲")).to_text().replace("title:", "slug: 丙\ntitle:", 1),
        encoding="utf-8",
    )
    page = store.load("甲")
    assert any(d.code == "E103" for d in page.diagnostics)


def test_new_sections_are_separated_by_blank_lines(store: WikiStore) -> None:
    store.create("甲", body="## 小节\n原有内容。\n")
    store.update("甲", lambda ed: ed.add_seealso("乙"))
    text = store.text_for("甲")
    assert "\n---\n\n@ 序言" in text, "front matter 与第一个板块之间要有空行"
    assert "\n\n@ 参见" in text, "新板块前要补一个空行"
    assert "\n\n@ 编辑记录" not in text  # 没加日志就不该凭空出现板块

