"""静态站点导出：把整个 wiki 渲染成可直接双击浏览的 HTML 目录。

产出结构（全部平铺，避免相对路径陷阱）::

    out/
      index.html          # 分类首页
      <slug>.html         # 每个条目一页
      tag-<标签>.html     # 每个标签一页
      assets/style.css
      index.json          # 给前端/搜索用
"""

from __future__ import annotations

import shutil
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .index import WikiIndex
from .render.html import ASSETS_DIR, render_page
from .store import slugify_title


@dataclass
class ExportResult:
    """一次导出的产物清单。"""

    out_dir: Path
    pages: list[Path] = field(default_factory=list)
    tags: list[Path] = field(default_factory=list)
    index_html: Path | None = None
    index_json: Path | None = None
    css: Path | None = None

    @property
    def count(self) -> int:
        return len(self.pages)


def _jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader([str(ASSETS_DIR)]),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")


def export_page(
    store,
    slug: str,
    out_dir: str | Path,
    *,
    with_related: bool = False,
    site_name: str = "",
    mathjax: bool = False,
    toc_depth: int = 3,
    index: WikiIndex | None = None,
) -> ExportResult:
    """只导出**一个**页面（可选带上它的出链与反链页面），不重建整站。

    ``with_related=True`` 时额外导出：这页引用到的页面（一跳）＋引用这页的页面（反链）。
    这样导出的 HTML 里的链接至少一跳之内不会 404。
    注意：单页导出不生成标签页，所以标签渲染成不可点的 ``.tag`` span。
    """
    wiki = index or WikiIndex(store)
    page = store.load(slug)

    targets: list[str] = [slug]
    if with_related:
        for link in page.links():
            resolved = wiki.resolve(link.target)
            if resolved is not None and resolved not in targets:
                targets.append(resolved)
        for source in wiki.backlinks(slug):
            if source not in targets:
                targets.append(source)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    assets = out / "assets"
    assets.mkdir(exist_ok=True)
    css = assets / "style.css"
    shutil.copyfile(ASSETS_DIR / "style.css", css)

    result = ExportResult(out_dir=out, css=css)

    def tag_href(tag: str) -> str | None:
        """只有输出目录里真的存在该标签页时，才把标签做成链接。"""
        name = f"tag-{slugify_title(tag)}.html"
        return name if (out / name).is_file() else None

    for target in targets:
        rendered = render_page(
            store.load(target),
            resolver=wiki.resolver,
            backlinks=wiki.backlink_pairs(target),
            toc_depth=toc_depth,
            tag_href=tag_href,
            css_href="assets/style.css",
            site_name=site_name,
            mathjax=mathjax,
        )
        path = out / f"{target}.html"
        path.write_text(rendered.full_html, encoding="utf-8")
        result.pages.append(path)
    return result


def export_site(
    store,
    out_dir: str | Path,
    *,
    site_name: str = "",
    mathjax: bool = False,
    toc_depth: int = 3,
    index: WikiIndex | None = None,
) -> ExportResult:
    """渲染全站。``out_dir`` 会被覆盖同名文件，但不会清理旧文件。"""
    wiki = index or WikiIndex(store)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    assets = out / "assets"
    assets.mkdir(exist_ok=True)
    css = assets / "style.css"
    shutil.copyfile(ASSETS_DIR / "style.css", css)

    result = ExportResult(out_dir=out, css=css)
    css_href = "assets/style.css"

    def tag_href(tag: str) -> str:
        return f"tag-{slugify_title(tag)}.html"

    for slug in sorted(wiki.pages):
        page = wiki.raw[slug]
        rendered = render_page(
            page,
            resolver=wiki.resolver,
            backlinks=wiki.backlink_pairs(slug),
            toc_depth=toc_depth,
            tag_href=tag_href,
            css_href=css_href,
            site_name=site_name,
            mathjax=mathjax,
        )
        path = out / f"{slug}.html"
        path.write_text(rendered.full_html, encoding="utf-8")
        result.pages.append(path)

    env = _jinja_env()
    template = env.get_template("list.html")
    stamp = _timestamp()

    # --- 标签页 ---
    for tag, slugs in wiki.tags().items():
        groups = [
            {
                "title": f"#{tag}",
                "items": [
                    {
                        "href": f"{slug}.html",
                        "title": wiki.pages[slug].title,
                        "meta": wiki.pages[slug].kind,
                    }
                    for slug in sorted(slugs, key=lambda s: wiki.pages[s].title)
                ],
            }
        ]
        html = template.render(
            heading=f"标签：{tag}",
            subtitle=f"共 {len(slugs)} 个条目",
            groups=groups,
            site_name=site_name,
            css_href=css_href,
            generated_at=stamp,
            home_href="index.html",
        )
        path = out / f"tag-{slugify_title(tag)}.html"
        path.write_text(html, encoding="utf-8")
        result.tags.append(path)

    # --- 首页 ---
    by_kind: dict[str, list[dict]] = defaultdict(list)
    for entry in wiki.pages.values():
        by_kind[entry.kind or "其他条目"].append(
            {
                "href": f"{entry.slug}.html",
                "title": entry.title,
                "meta": entry.excerpt,
            }
        )
    groups = [
        {
            "title": kind,
            "items": sorted(items, key=lambda item: item["title"]),
        }
        for kind, items in sorted(by_kind.items())
    ]
    index_html = out / "index.html"
    index_html.write_text(
        template.render(
            heading=site_name or "知识库",
            subtitle=f"共 {len(wiki.pages)} 个条目 · {len(wiki.tags())} 个标签",
            groups=groups,
            site_name=site_name,
            css_href=css_href,
            generated_at=stamp,
            home_href="",
        ),
        encoding="utf-8",
    )
    result.index_html = index_html

    result.index_json = wiki.save(out / "index.json")
    return result
