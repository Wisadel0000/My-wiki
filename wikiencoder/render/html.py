"""WikiPage → HTML。

对外只有一个入口 :func:`render_page`，返回 :class:`RenderedPage`：
九段彼此独立的 HTML 字符串（前端可以随便挑着放），外加一份整页文档。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from urllib.parse import urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .. import syntax as S
from ..infobox import InfoboxField
from ..links import WikiLink
from ..log import EditRecord
from ..model import WikiPage
from ..toc import Heading
from .markdown import (
    ResolveFn,
    build_anchor,
    build_markdown,
    default_resolver,
    render_inline,
    render_text,
)

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"

#: 信息框里优先展示的键（其余按文件顺序排在后面）
INFOBOX_PRIORITY: tuple[str, ...] = (
    "领域",
    "从属领域",
    "学科",
    "父级",
    "父级知识点",
    "上级",
    "属性",
    "相关概念",
    "相关",
    "应用",
    "应用场景",
)

#: 标签不进信息框正文键值（由 front matter 的 tags 生成）
TAG_KEYS = ("标签", "tags")


@dataclass
class RenderedPage:
    """一次渲染的全部产物。"""

    slug: str
    title: str
    kind: str = ""
    tags: list[str] = field(default_factory=list)
    meta_html: str = ""
    lead_html: str = ""
    infobox_html: str = ""
    toc_html: str = ""
    body_html: str = ""
    seealso_html: str = ""
    sources_html: str = ""
    log_html: str = ""
    backlinks_html: str = ""
    full_html: str = ""

    PARTS: tuple[str, ...] = (
        "meta_html",
        "lead_html",
        "infobox_html",
        "toc_html",
        "body_html",
        "seealso_html",
        "sources_html",
        "log_html",
        "backlinks_html",
    )

    @property
    def parts(self) -> dict[str, str]:
        """``{"lead_html": ..., "body_html": ...}``，方便前端按名取用。"""
        return {name: getattr(self, name) for name in self.PARTS}


def _jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader([str(ASSETS_DIR)]),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _section_content(md, section, env: dict) -> str:
    """渲染一个板块的正文（按 ``:::`` 区域分别处理）。"""
    chunks: list[str] = []
    for region in S.iter_regions(
        section.body, section.effective_mode, base_line=section.line + 1
    ):
        if region.mode == "md":
            chunks.append(md.render(region.text, env))
        else:
            chunks.append(render_text(region.text, env))
    return "\n".join(chunk for chunk in chunks if chunk.strip())


# --- 各板块 ---------------------------------------------------------------
def _lead_html(page: WikiPage, md, env: dict) -> str:
    preamble = page.get_section(S.PREAMBLE)
    if preamble is not None:
        inner = _section_content(md, preamble, env)
    elif page.prologue_raw.strip():
        inner = md.render(page.prologue_raw, env)
    else:
        return ""
    if not inner.strip():
        return ""
    return f'<div class="wiki-lead">\n{inner}\n</div>'


def _infobox_fields(page: WikiPage) -> list[InfoboxField]:
    fields = [f for f in page.infobox_fields() if f.key not in TAG_KEYS]
    rank = {key: index for index, key in enumerate(INFOBOX_PRIORITY)}
    indexed = list(enumerate(fields))
    indexed.sort(key=lambda pair: (rank.get(pair[1].key, len(rank)), pair[0]))
    return [item for _, item in indexed]


def _infobox_html(
    page: WikiPage,
    md,
    env: dict,
    *,
    tag_href: Callable[[str], str | None] | None,
) -> str:
    rows: list[str] = []
    for item in _infobox_fields(page):
        value = render_inline(item.value, env, md=md)
        rows.append(
            f'<div class="wiki-infobox-row" data-key="{escape(item.key)}">'
            f"<dt>{escape(item.key)}</dt><dd>{value}</dd></div>"
        )

    tags = page.tags
    if tags:
        chips = "".join(_tag_chip(tag, tag_href) for tag in tags)
        rows.append(
            '<div class="wiki-infobox-row wiki-infobox-tags" data-key="标签">'
            f'<dt>标签</dt><dd class="wiki-tags">{chips}</dd></div>'
        )

    if not rows:
        return ""
    return (
        '<aside class="wiki-infobox" aria-label="标识信息框">\n<dl>\n'
        + "\n".join(rows)
        + "\n</dl>\n</aside>"
    )


def _tag_chip(tag: str, tag_href: Callable[[str], str | None] | None) -> str:
    label = escape(tag if tag.startswith("#") else f"#{tag}")
    if tag_href is None:
        return f'<span class="tag">{label}</span>'
    href = tag_href(tag)
    if href is None:  # 对应的标签页不存在 → 渲染成不可点的 span
        return f'<span class="tag">{label}</span>'
    return f'<a class="tag" href="{escape(href, quote=True)}">{label}</a>'


def _build_toc(nodes: list[dict], depth: int) -> str:
    out = ['<ol class="wiki-toc-list">']
    for node in nodes:
        heading: Heading = node["heading"]
        out.append(
            '<li class="wiki-toc-item">'
            f'<a href="#{escape(heading.anchor)}">{escape(heading.text)}</a>'
        )
        if node["children"]:
            out.append(_build_toc(node["children"], depth + 1))
        out.append("</li>")
    out.append("</ol>")
    return "".join(out)


def _toc_tree(headings: list[Heading]) -> list[dict]:
    root: list[dict] = []
    stack: list[tuple[int, list[dict]]] = [(0, root)]
    for heading in headings:
        while stack and stack[-1][0] >= heading.level:
            stack.pop()
        node = {"heading": heading, "children": []}
        (stack[-1][1] if stack else root).append(node)
        stack.append((heading.level, node["children"]))
    return root


def _toc_html(headings: list[Heading], *, depth: int) -> str:
    items = [h for h in headings if h.level <= depth]
    if not items:
        return ""
    tree = _toc_tree(items)
    return (
        '<nav class="wiki-toc" aria-label="目录">\n'
        '<div class="wiki-toc-title">目录</div>\n'
        f"{_build_toc(tree, 2)}\n</nav>"
    )


def _body_html(page: WikiPage, md, env: dict) -> str:
    chunks: list[str] = []
    for section in page.sections:
        if section.key == S.BODY:
            chunks.append(_section_content(md, section, env))
        elif section.is_extra:
            title = escape(section.title)
            chunks.append(
                f'<section class="wiki-extra" data-section="{title}">\n'
                f'<h2 class="wiki-section-title">{title}</h2>\n'
                f"{_section_content(md, section, env)}\n</section>"
            )
    inner = "\n".join(chunk for chunk in chunks if chunk.strip())
    if not inner.strip():
        return ""
    return f'<section class="wiki-body" id="wiki-body">\n{inner}\n</section>'


def _seealso_html(page: WikiPage, env: dict) -> str:
    items = page.seealso_items()
    if not items:
        return ""
    rows: list[str] = []
    for item in items:
        if item.is_link:
            link = _anchor_from_parts(item.target, item.anchor, item.label, env)
        else:
            link = escape(item.target)
        note = f' <span class="wiki-note">{escape(item.note)}</span>' if item.note else ""
        rows.append(f"<li>{link}{note}</li>")
    return (
        '<section class="wiki-seealso" id="wiki-seealso">\n'
        '<h2 class="wiki-section-title">参见</h2>\n<ul class="wiki-seealso-list">\n'
        + "\n".join(rows)
        + "\n</ul>\n</section>"
    )


def _anchor_from_parts(
    target: str, anchor: str | None, label: str | None, env: dict
) -> str:
    return build_anchor(WikiLink(target=target, anchor=anchor, label=label), env)


def _sources_html(page: WikiPage) -> str:
    items = page.source_items()
    if not items:
        return ""
    rows: list[str] = []
    for item in items:
        kind = (
            f'<span class="wiki-source-kind">{escape(item.kind)}</span> '
            if item.kind
            else ""
        )
        text = escape(item.text)
        if item.url:
            host = escape(urlparse(item.url).netloc or item.url)
            href = escape(item.url, quote=True)
            anchor = (
                f'<a class="wiki-source-url" href="{href}" '
                f'rel="noreferrer noopener" target="_blank">{host}</a>'
            )
            text = anchor if item.text.strip() == item.url else f"{text} {anchor}"
        rows.append(f"<li>{kind}{text}</li>")
    return (
        '<section class="wiki-sources" id="wiki-sources">\n'
        '<h2 class="wiki-section-title">知识来源</h2>\n<ul class="wiki-source-list">\n'
        + "\n".join(rows)
        + "\n</ul>\n</section>"
    )


def _log_html(page: WikiPage) -> str:
    section = page.get_section(S.LOG)
    records: list[EditRecord] = page.edit_records()
    if section is None and not records:
        return ""
    summary = f"共 {len(records)} 次修改" if records else "暂无编辑记录"
    head = (
        '<section class="wiki-log" id="wiki-log">\n'
        '<h2 class="wiki-section-title">编辑记录</h2>\n'
        f'<p class="wiki-log-summary">{summary}</p>'
    )
    if not records:
        return head + "\n</section>"
    rows = "\n".join(
        "<tr>"
        f'<td class="n">{record.n}</td>'
        f'<td class="date">{escape(record.date or "—")}</td>'
        f'<td class="author">{escape(record.author or "—")}</td>'
        f'<td class="message">{escape(record.message)}</td>'
        "</tr>"
        for record in records
    )
    table = (
        '<table class="wiki-log-table">\n<thead><tr>'
        "<th>#</th><th>日期</th><th>作者</th><th>说明</th>"
        "</tr></thead>\n<tbody>\n"
        f"{rows}\n"
        "</tbody>\n</table>"
    )
    return f"{head}\n{table}\n</section>"


def _backlinks_html(
    backlinks: Sequence[tuple[str, str]], env: dict
) -> str:
    if not backlinks:
        return ""
    resolver: ResolveFn = env.get("resolve") or default_resolver
    rows: list[str] = []
    for target, title in backlinks:
        href, broken = resolver(target, None)
        classes = "wikilink broken" if broken else "wikilink"
        rows.append(
            f'<li><a class="{classes}" href="{escape(href, quote=True)}">'
            f"{escape(title or target)}</a></li>"
        )
    return (
        '<section class="wiki-backlinks" id="wiki-backlinks">\n'
        '<h2 class="wiki-section-title">被以下条目引用</h2>\n<ul>\n'
        + "\n".join(rows)
        + "\n</ul>\n</section>"
    )


def _meta_html(page: WikiPage, records: list[EditRecord]) -> str:
    bits: list[str] = []
    if page.kind:
        bits.append(f'<span class="wiki-kind">{escape(page.kind)}</span>')
    updated = records[-1].date if records else page.created
    if updated:
        bits.append(f'<span class="wiki-updated">更新于 {escape(updated)}</span>')
    if records:
        bits.append(f'<span class="wiki-edit-count">{len(records)} 次编辑</span>')
    if not bits:
        return ""
    return '<div class="wiki-meta">' + " · ".join(bits) + "</div>"


# --- 入口 -----------------------------------------------------------------
def render_page(
    page: WikiPage,
    *,
    resolver: ResolveFn | None = None,
    backlinks: Sequence[tuple[str, str]] = (),
    toc_depth: int = 3,
    toc: bool = True,
    tag_href: Callable[[str], str | None] | None = None,
    template: str = "page.html",
    css_href: str | None = "assets/style.css",
    css_inline: str | None = None,
    mathjax: bool = False,
    site_name: str = "",
    generated_at: str | None = None,
    anchors: dict[str, int] | None = None,
) -> RenderedPage:
    """渲染一个页面。传入 ``resolver`` 才能标出红链（未创建页面）。"""
    env: dict = {
        "resolve": resolver or default_resolver,
        "anchors": {} if anchors is None else anchors,
    }
    md = build_markdown()

    result = RenderedPage(
        slug=page.slug,
        title=page.title,
        kind=page.kind,
        tags=list(page.tags),
    )
    result.meta_html = _meta_html(page, page.edit_records())
    result.lead_html = _lead_html(page, md, env)
    result.infobox_html = _infobox_html(page, md, env, tag_href=tag_href)
    result.body_html = _body_html(page, md, env)
    if toc:
        result.toc_html = _toc_html(page.headings(), depth=toc_depth)
    result.seealso_html = _seealso_html(page, env)
    result.sources_html = _sources_html(page)
    result.log_html = _log_html(page)
    result.backlinks_html = _backlinks_html(backlinks, env)

    from datetime import UTC, datetime

    timestamp = generated_at or datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    html = _jinja_env().get_template(template).render(
        slug=result.slug,
        title=result.title,
        kind=result.kind,
        site_name=site_name,
        meta_html=result.meta_html,
        lead_html=result.lead_html,
        infobox_html=result.infobox_html,
        toc_html=result.toc_html,
        body_html=result.body_html,
        seealso_html=result.seealso_html,
        sources_html=result.sources_html,
        log_html=result.log_html,
        backlinks_html=result.backlinks_html,
        css_href=css_href,
        css_inline=css_inline,
        mathjax=mathjax,
        generated_at=timestamp,
    )
    result.full_html = html
    return result


def render_body(page: WikiPage, **kwargs) -> str:
    """只要正文那一段（给 SPA 用）。"""
    return render_page(page, **kwargs).body_html


def render_parts(page: WikiPage, **kwargs) -> dict[str, str]:
    """只要九段 HTML 字典（等价于 ``render_page(page).parts``）。"""
    return render_page(page, **kwargs).parts


def render_fragment(text: str, *, mode: str = "md", env: dict | None = None) -> str:
    """把任意 markdown / 纯文本片段渲染成 HTML（独立小工具）。"""
    context = env if env is not None else {"anchors": {}}
    if mode == "text":
        return render_text(text, context)
    return build_markdown().render(text, context)
