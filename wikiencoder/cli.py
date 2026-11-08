"""命令行接口。

设计原则：每个写命令都支持 ``--dry-run``（只输出 diff）与 ``--json``（机器可读），
失败一律返回退出码 1 —— 这样 agent 可以直接把 CLI 当 API 用。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .errors import WikiError
from .render.html import ASSETS_DIR
from .store import OpResult, WikiStore

EXIT_OK = 0
EXIT_FAIL = 1


# --- 公共 ---
def _store(args: argparse.Namespace) -> WikiStore:
    return WikiStore(args.root, author=getattr(args, "author", ""))


def _emit(data: dict | list, *, as_json: bool) -> None:
    del as_json  # 目前只有 JSON 一种输出，保留参数是为了将来加表格
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _finish(result: OpResult, args: argparse.Namespace) -> int:
    if not result.ok:
        for error in result.errors:
            print(f"错误：{error}", file=sys.stderr)
        return EXIT_FAIL
    if getattr(args, "json", False):
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    elif result.changed:
        print(result.diff or "已更新")
    else:
        print("没有变化")
    return EXIT_OK


def _read_text(args: argparse.Namespace) -> str:
    if getattr(args, "text", None):
        return args.text
    return sys.stdin.read()


# --- 各子命令 ---
def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.root)
    store = WikiStore(root)
    store.pages_dir.mkdir(parents=True, exist_ok=True)
    assets = root / "assets"
    assets.mkdir(exist_ok=True)
    css = assets / "style.css"
    if not css.exists():
        css.write_bytes((ASSETS_DIR / "style.css").read_bytes())
    for name in ("SYNTAX.md", "AGENTS.md"):
        target = root / name
        if not target.exists():
            target.write_bytes((ASSETS_DIR / name).read_bytes())
    config = root / "wiki.toml"
    if not config.exists() and not args.force:
        config.write_text(
            '[wiki]\npages = "pages"\nauthor = ""\n\n[render]\ntoc_depth = 3\nmath = false\n',
            encoding="utf-8",
        )
    print(f"初始化完成：{root.resolve()}")
    return EXIT_OK


def cmd_new(args: argparse.Namespace) -> int:
    store = _store(args)
    result = store.create(
        args.title,
        slug=args.slug,
        kind=args.type,
        tags=[tag.strip() for tag in args.tags.split(",") if tag.strip()],
        preamble=args.preamble,
        body=args.body,
        dry_run=args.dry_run,
    )
    return _finish(result, args)


def cmd_list(args: argparse.Namespace) -> int:
    store = _store(args)
    rows = []
    for slug in store.slugs():
        page = store.load(slug)
        rows.append({"slug": slug, "title": page.title, "type": page.kind, "tags": page.tags})
    if args.json:
        _emit(rows, as_json=True)
    else:
        for row in rows:
            print(f"{row['slug']}\t{row['title']}\t{row['type']}\t{','.join(row['tags'])}")
        print(f"共 {len(rows)} 个条目")
    return EXIT_OK


def cmd_show(args: argparse.Namespace) -> int:
    store = _store(args)
    page = store.load(args.slug)
    if args.html:
        from .render import render_page

        print(render_page(page).full_html)
        return EXIT_OK
    if args.json:
        _emit(
            {
                "slug": page.slug,
                "title": page.title,
                "type": page.kind,
                "tags": page.tags,
                "aliases": page.aliases,
                "sections": page.section_keys(),
                "infobox": page.infobox_dict(),
                "records": len(page.edit_records()),
                "diagnostics": [str(item) for item in page.diagnostics],
            },
            as_json=True,
        )
        return EXIT_OK
    print(page.to_text())
    return EXIT_OK


def cmd_set(args: argparse.Namespace) -> int:
    store = _store(args)
    text = _read_text(args)
    if args.append:
        return _finish(
            store.update(
                args.slug,
                lambda ed: ed.append_section(args.section, text),
                dry_run=args.dry_run,
            ),
            args,
        )
    return _finish(
        store.update(
            args.slug,
            lambda ed: ed.set_section(args.section, text),
            dry_run=args.dry_run,
        ),
        args,
    )


def cmd_infobox(args: argparse.Namespace) -> int:
    store = _store(args)
    if args.action == "rm":
        return _finish(
            store.update(args.slug, lambda ed: ed.remove_infobox(args.key), dry_run=args.dry_run),
            args,
        )
    return _finish(
        store.update(
            args.slug, lambda ed: ed.set_infobox(args.key, args.value or ""), dry_run=args.dry_run
        ),
        args,
    )


def cmd_tag(args: argparse.Namespace) -> int:
    store = _store(args)
    if args.action == "rm":
        return _finish(
            store.update(args.slug, lambda ed: ed.remove_tag(args.tag), dry_run=args.dry_run),
            args,
        )
    return _finish(
        store.update(args.slug, lambda ed: ed.add_tag(args.tag), dry_run=args.dry_run), args
    )


def cmd_log(args: argparse.Namespace) -> int:
    store = _store(args)
    if args.action == "list":
        page = store.load(args.slug)
        records = [
            {"n": item.n, "date": item.date, "author": item.author, "message": item.message}
            for item in page.edit_records()
        ]
        if args.json:
            _emit(records, as_json=True)
        else:
            for record in records:
                print(f"{record['n']}\t{record['date']}\t{record['author']}\t{record['message']}")
        return EXIT_OK
    if args.action == "rm":
        number = args.number or (int(args.message) if args.message.isdigit() else 0)
        return _finish(
            store.update(
                args.slug, lambda ed: ed.remove_edit_record(number), dry_run=args.dry_run
            ),
            args,
        )
    return _finish(
        store.update(
            args.slug,
            lambda ed: ed.add_edit_record(args.message, date=args.date, author=args.author_name),
            dry_run=args.dry_run,
        ),
        args,
    )


def cmd_see(args: argparse.Namespace) -> int:
    store = _store(args)
    if args.action == "rm":
        return _finish(
            store.update(
                args.slug,
                lambda ed: ed.remove_seealso(args.target),
                dry_run=args.dry_run,
            ),
            args,
        )
    return _finish(
        store.update(
            args.slug,
            lambda ed: ed.add_seealso(args.target, note=args.note or ""),
            dry_run=args.dry_run,
        ),
        args,
    )


def cmd_source(args: argparse.Namespace) -> int:
    store = _store(args)
    return _finish(
        store.update(
            args.slug,
            lambda ed: ed.add_source(args.kind, args.text, url=args.url),
            dry_run=args.dry_run,
        ),
        args,
    )


def cmd_link(args: argparse.Namespace) -> int:
    from .index import WikiIndex

    store = _store(args)
    index = WikiIndex(store)
    broken = [
        {"from": slug, "target": link.target, "line": link.line}
        for slug, link in index.broken_links()
    ]
    anchors = [
        {"from": slug, "target": link.target, "anchor": link.anchor, "line": link.line}
        for slug, link in index.broken_anchors()
    ]
    if args.json:
        _emit({"broken": broken, "anchors": anchors}, as_json=True)
    else:
        for item in broken:
            print(f"[红链] {item['from']}:{item['line']} -> [[{item['target']}]]")
        for item in anchors:
            print(f"[锚点] {item['from']}:{item['line']} -> [[{item['target']}#{item['anchor']}]]")
        print(f"红链 {len(broken)} 条，失效锚点 {len(anchors)} 条")
    return EXIT_FAIL if (broken or anchors) and args.strict else EXIT_OK


def cmd_rename(args: argparse.Namespace) -> int:
    store = _store(args)
    return _finish(store.rename(args.old, args.new, dry_run=args.dry_run), args)


def cmd_validate(args: argparse.Namespace) -> int:
    from .validate import validate_store

    store = _store(args)
    report = validate_store(store)
    if args.json:
        _emit(report.to_dict(), as_json=True)
    else:
        print(report)
    if not report.ok:
        return EXIT_FAIL
    if args.strict and report.warnings:
        return EXIT_FAIL
    return EXIT_OK


def cmd_index(args: argparse.Namespace) -> int:
    from .index import WikiIndex

    store = _store(args)
    index = WikiIndex(store)
    if args.only_build:
        path = index.save()
        print(f"已写入 {path}（{len(index)} 个条目）")
        return EXIT_OK
    if args.json:
        _emit(index.to_json(), as_json=True)
    else:
        print(f"条目 {len(index)}，边 {len(index.edges)}，标签 {len(index.tags())}")
        for slug, entry in index.pages.items():
            print(f"  {slug}: 入链 {len(entry.backlinks)} / 出链 {len(entry.links_out)}")
    return EXIT_OK


def cmd_kinds(args: argparse.Namespace) -> int:
    """列出全库已有的 kind（front matter 的 type），便于新建时选类型。"""
    from .index import UNCLASSIFIED, WikiIndex

    store = _store(args)
    index = WikiIndex(store)
    groups = index.kinds()
    if args.json:
        _emit(
            {
                kind: [
                    {"slug": slug, "title": index.pages[slug].title} for slug in slugs
                ]
                for kind, slugs in groups.items()
            },
            as_json=True,
        )
        return EXIT_OK
    for kind, slugs in groups.items():
        titles = "、".join(sorted(index.pages[slug].title for slug in slugs))
        print(f"{kind}\t{len(slugs)}\t{titles}")
    suffix = f"（其中「{UNCLASSIFIED}」是没有写 type 的）" if UNCLASSIFIED in groups else ""
    print(f"共 {len(groups)} 种 kind{suffix}")
    return EXIT_OK


def cmd_search(args: argparse.Namespace) -> int:
    from .index import WikiIndex

    store = _store(args)
    index = WikiIndex(store)
    hits = index.search(args.query, limit=args.limit)
    if args.json:
        _emit([entry.to_dict() for entry in hits], as_json=True)
    else:
        for entry in hits:
            print(f"{entry.slug}\t{entry.title}\t{entry.excerpt}")
        print(f"命中 {len(hits)} 条")
    return EXIT_OK if hits else EXIT_FAIL


def cmd_build(args: argparse.Namespace) -> int:
    from .export import export_page, export_site

    store = _store(args)
    if args.with_related and not args.only:
        print("错误：--with-related 需要配合 --only 使用", file=sys.stderr)
        return EXIT_FAIL

    if args.only:
        result = export_page(
            store,
            args.only,
            args.out,
            with_related=args.with_related,
            site_name=args.site_name,
            mathjax=args.mathjax,
            toc_depth=args.toc_depth,
        )
    else:
        result = export_site(
            store,
            args.out,
            site_name=args.site_name,
            mathjax=args.mathjax,
            toc_depth=args.toc_depth,
        )

    if args.json:
        _emit(
            {
                "out_dir": str(result.out_dir),
                "pages": [str(path) for path in result.pages],
                "tags": [str(path) for path in result.tags],
                "index": str(result.index_html) if result.index_html else None,
            },
            as_json=True,
        )
    elif args.only:
        names = "、".join(path.stem for path in result.pages)
        print(f"已导出 {result.count} 个页面 → {result.out_dir}（{names}）")
    else:
        print(f"已导出 {result.count} 个页面、{len(result.tags)} 个标签页 → {result.out_dir}")
    return EXIT_OK


def cmd_spec(args: argparse.Namespace) -> int:
    doc = ASSETS_DIR / "SYNTAX.md"
    if doc.is_file():
        print(doc.read_text(encoding="utf-8"))
    else:
        print("语法规范尚未安装（缺少 assets/SYNTAX.md）。")
    return EXIT_OK


# --- 解析器 ---
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wikiencoder", description="纯文本 wiki 框架")
    parser.add_argument("--version", action="version", version=f"wikiencoder {__version__}")
    parser.add_argument("--root", default=".", help="wiki 根目录（默认当前目录）")
    parser.add_argument("--author", default="", help="写入编辑记录时使用的默认作者")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, func, help_text: str) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, help=help_text)
        sp.set_defaults(_handler=func, json=False)
        return sp

    def write_flags(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--dry-run", action="store_true", help="只输出 diff，不写盘")
        sp.add_argument("--json", action="store_true", help="JSON 输出")

    sp = add("init", cmd_init, "初始化 wiki 目录")
    sp.add_argument("--force", action="store_true")

    sp = add("new", cmd_new, "新建条目")
    sp.add_argument("title")
    sp.add_argument("--slug")
    sp.add_argument("--type", default="")
    sp.add_argument("--tags", default="")
    sp.add_argument("--preamble")
    sp.add_argument("--body")
    write_flags(sp)

    add("list", cmd_list, "列出所有条目")

    sp = add("show", cmd_show, "显示条目")
    sp.add_argument("slug")
    sp.add_argument("--html", action="store_true", help="输出完整 HTML")
    sp.add_argument("--json", action="store_true")

    sp = add("set", cmd_set, "设置/追加板块内容（stdin 或 --text）")
    sp.add_argument("slug")
    sp.add_argument("section")
    sp.add_argument("--text")
    sp.add_argument("--append", action="store_true")
    write_flags(sp)

    sp = add("infobox", cmd_infobox, "设置/删除信息框字段")
    sp.add_argument("slug")
    sp.add_argument("action", choices=["set", "rm"])
    sp.add_argument("key")
    sp.add_argument("value", nargs="?")
    write_flags(sp)

    sp = add("tag", cmd_tag, "增删标签")
    sp.add_argument("slug")
    sp.add_argument("action", choices=["add", "rm"])
    sp.add_argument("tag")
    write_flags(sp)

    sp = add("log", cmd_log, "编辑记录：add / list / rm")
    sp.add_argument("slug")
    sp.add_argument("action", choices=["add", "list", "rm"])
    sp.add_argument("message", nargs="?", default="")
    sp.add_argument("number", nargs="?", type=int, default=0)
    sp.add_argument("--date")
    sp.add_argument("--author-name", dest="author_name")
    write_flags(sp)

    sp = add("see", cmd_see, "参见：add / rm")
    sp.add_argument("slug")
    sp.add_argument("action", choices=["add", "rm"])
    sp.add_argument("target")
    sp.add_argument("--note")
    write_flags(sp)

    sp = add("source", cmd_source, "追加知识来源")
    sp.add_argument("slug")
    sp.add_argument("text")
    sp.add_argument("--kind")
    sp.add_argument("--url")
    write_flags(sp)

    sp = add("link", cmd_link, "检查红链与失效锚点")
    sp.add_argument("--strict", action="store_true")

    sp = add("rename", cmd_rename, "重命名并同步全库引用")
    sp.add_argument("old")
    sp.add_argument("new")
    write_flags(sp)

    sp = add("validate", cmd_validate, "整库校验")
    sp.add_argument("--strict", action="store_true")

    sp = add("index", cmd_index, "构建/查看索引")
    sp.add_argument("--build", dest="only_build", action="store_true")
    sp.add_argument("--json", action="store_true")

    sp = add("kinds", cmd_kinds, "列出全库已有的 kind（类型）")
    sp.add_argument("--json", action="store_true")

    sp = add("search", cmd_search, "搜索条目")
    sp.add_argument("query")
    sp.add_argument("--limit", type=int, default=20)
    sp.add_argument("--json", action="store_true")

    sp = add("build", cmd_build, "导出静态站点（或只导一个页面）")
    sp.add_argument("-o", "--out", default="out")
    sp.add_argument("--only", help="只导出这一页（写 slug）")
    sp.add_argument(
        "--with-related",
        dest="with_related",
        action="store_true",
        help="配合 --only：连它的一跳出链与反链一起导出",
    )
    sp.add_argument("--site-name", default="")
    sp.add_argument("--mathjax", action="store_true")
    sp.add_argument("--toc-depth", type=int, default=3)
    sp.add_argument("--json", action="store_true")

    add("spec", cmd_spec, "打印语法规范")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args._handler(args))
    except (WikiError, FileNotFoundError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return EXIT_FAIL


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
