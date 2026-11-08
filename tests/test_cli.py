"""CLI 与静态导出测试。"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest

from wikiencoder.cli import main
from wikiencoder.export import export_page, export_site
from wikiencoder.store import WikiStore


@pytest.fixture()
def root() -> Iterator[Path]:
    path = Path(".pytest-tmp") / f"cli-{uuid4().hex[:8]}"
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def run(root: Path, *argv: str) -> int:
    return main(["--root", str(root), "--author", "我", *argv])


def test_init_creates_layout(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(root, "init") == 0
    assert (root / "pages").is_dir()
    assert (root / "assets" / "style.css").is_file()
    assert (root / "assets" / "style.css").stat().st_size > 1000
    assert (root / "SYNTAX.md").is_file()
    assert (root / "AGENTS.md").is_file()
    assert "初始化完成" in capsys.readouterr().out


def test_new_and_list(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(root, "init")
    assert run(root, "new", "傅里叶变换", "--type", "概念", "--tags", "变换,数学") == 0
    capsys.readouterr()
    assert run(root, "list") == 0
    out = capsys.readouterr().out
    assert "傅里叶变换" in out
    assert "共 1 个条目" in out


def test_edit_commands_round_trip(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(root, "init")
    run(root, "new", "甲")
    capsys.readouterr()
    assert run(root, "tag", "甲", "add", "测试") == 0
    assert run(root, "infobox", "甲", "set", "领域", "数学") == 0
    assert run(root, "log", "甲", "add", "初始版本") == 0
    assert run(root, "see", "甲", "add", "乙", "--note", "相关") == 0
    capsys.readouterr()

    assert run(root, "show", "甲", "--json") == 0
    data = json.loads(capsys.readouterr().out)
    assert data["tags"] == ["测试"]
    assert data["infobox"] == {"领域": "数学"}
    assert data["records"] == 1
    assert "seealso" in data["sections"]


def test_dry_run_does_not_touch_disk(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(root, "init")
    run(root, "new", "甲")
    capsys.readouterr()
    before = (root / "pages" / "甲.wiki").read_bytes()
    assert run(root, "tag", "甲", "add", "新标签", "--dry-run") == 0
    out = capsys.readouterr().out
    assert "+tags:" in out
    assert (root / "pages" / "甲.wiki").read_bytes() == before


def test_rename_command(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(root, "init")
    run(root, "new", "甲")
    run(root, "new", "乙", "--body", "见 [[甲]]")
    capsys.readouterr()
    assert run(root, "rename", "甲", "甲二") == 0
    assert (root / "pages" / "甲二.wiki").is_file()
    assert "[[甲二]]" in (root / "pages" / "乙.wiki").read_text(encoding="utf-8")


def test_validate_and_link_exit_codes(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(root, "init")
    run(root, "new", "甲", "--body", "见 [[幽灵]]")
    capsys.readouterr()
    assert run(root, "validate") == 0  # 红链只是 warning
    assert run(root, "link") == 0
    assert run(root, "link", "--strict") == 1
    capsys.readouterr()


def test_index_and_search(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(root, "init")
    run(root, "new", "傅里叶变换", "--type", "概念", "--tags", "变换")
    capsys.readouterr()
    assert run(root, "index", "--build") == 0
    assert (root / "index.json").is_file()
    assert run(root, "search", "傅里叶") == 0
    assert "傅里叶变换" in capsys.readouterr().out
    assert run(root, "search", "找不到的东西") == 1


def test_build_exports_site(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(root, "init")
    run(root, "new", "傅里叶变换", "--type", "概念", "--tags", "变换", "--body", "## 定义\n内容。")
    run(root, "new", "积分变换", "--type", "概念", "--body", "见 [[傅里叶变换]]。")
    capsys.readouterr()

    out_dir = root / "out"
    assert run(root, "build", "-o", str(out_dir), "--site-name", "知识库") == 0
    assert (out_dir / "index.html").is_file()
    assert (out_dir / "傅里叶变换.html").is_file()
    assert (out_dir / "积分变换.html").is_file()
    assert (out_dir / "tag-变换.html").is_file()
    assert (out_dir / "assets" / "style.css").is_file()
    assert (out_dir / "index.json").is_file()

    page_html = (out_dir / "积分变换.html").read_text(encoding="utf-8")
    assert 'href="傅里叶变换.html"' in page_html
    assert "assets/style.css" in page_html
    assert "知识库" in (out_dir / "index.html").read_text(encoding="utf-8")


def test_export_site_api(root: Path) -> None:
    store = WikiStore(root)
    store.create("甲", body="## 节\n内容。\n")
    result = export_site(store, root / "site")
    assert result.count == 1
    assert result.index_html is not None and result.index_html.is_file()
    assert result.index_json is not None and result.index_json.is_file()
    data = json.loads(result.index_json.read_text(encoding="utf-8"))
    assert "甲" in data["pages"]


def test_export_page_only_one(root: Path) -> None:
    store = WikiStore(root)
    store.create("甲", body="见 [[乙]]。\n")
    store.create("乙", body="内容。\n")

    out = root / "one"
    result = export_page(store, "甲", out)
    assert [path.name for path in result.pages] == ["甲.html"]
    assert (out / "甲.html").is_file()
    assert not (out / "乙.html").exists()
    assert not (out / "index.html").exists()
    assert (out / "assets" / "style.css").is_file()


def test_export_page_with_related(root: Path) -> None:
    store = WikiStore(root)
    store.create("甲", body="见 [[乙]]。\n")
    store.create("乙", body="被甲引用。\n")
    store.create("丙", body="引用 [[甲]]。\n")

    result = export_page(store, "甲", root / "rel", with_related=True)
    assert sorted(path.name for path in result.pages) == ["丙.html", "乙.html", "甲.html"]
    html = (root / "rel" / "甲.html").read_text(encoding="utf-8")
    assert "被以下条目引用" in html
    assert 'href="乙.html"' in html


def test_export_page_keeps_existing_tag_links(root: Path) -> None:
    store = WikiStore(root)
    store.create("甲", tags=["数学"], body="内容。\n")
    out = root / "site"

    export_site(store, out)
    assert 'class="tag" href="tag-数学.html"' in (out / "甲.html").read_text(encoding="utf-8")

    export_page(store, "甲", out)
    again = (out / "甲.html").read_text(encoding="utf-8")
    assert 'class="tag" href="tag-数学.html"' in again, "已有标签页时不应退化成 span"

    fresh = root / "fresh"
    export_page(store, "甲", fresh)
    assert '<span class="tag">#数学</span>' in (fresh / "甲.html").read_text(encoding="utf-8")


def test_build_only_cli(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(root, "init")
    run(root, "new", "甲", "--body", "见 [[乙]]。")
    run(root, "new", "乙", "--body", "内容。")
    capsys.readouterr()

    assert run(root, "build", "-o", str(root / "out1"), "--only", "甲") == 0
    assert (root / "out1" / "甲.html").is_file()
    assert not (root / "out1" / "乙.html").exists()
    assert "已导出 1 个页面" in capsys.readouterr().out

    assert run(root, "build", "-o", str(root / "out2"), "--only", "甲", "--with-related") == 0
    assert (root / "out2" / "乙.html").is_file()

    assert run(root, "build", "--with-related") == 1


def test_spec_prints_documentation(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["spec"]) == 0
    out = capsys.readouterr().out
    assert "语法规范" in out
    assert "[[目标]]" in out


def test_kinds_command(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(root, "init")
    run(root, "new", "甲", "--type", "概念")
    run(root, "new", "乙", "--type", "定理")
    run(root, "new", "丙")
    capsys.readouterr()

    assert run(root, "kinds") == 0
    out = capsys.readouterr().out
    assert "概念" in out and "定理" in out
    assert "（未分类）" in out
    assert "共 3 种 kind" in out

    assert run(root, "kinds", "--json") == 0
    data = json.loads(capsys.readouterr().out)
    assert [item["title"] for item in data["概念"]] == ["甲"]
