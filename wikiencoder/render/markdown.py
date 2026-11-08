"""Markdown 渲染层。

三件事：
1. 建一个安全的 MarkdownIt（默认 ``html=False``，原始 HTML 一律转义）；
2. 注册 ``[[wikilink]]`` 行内规则，交给外层注入的 resolver 决定 href 与红链；
3. 让 ``##`` 标题生成中文锚点，且与目录共用同一个计数表（``env["anchors"]``）。
"""

from __future__ import annotations

from collections.abc import Callable
from html import escape

from markdown_it import MarkdownIt
from markdown_it.token import Token

from .. import syntax as S
from ..links import LINK_RE, WikiLink, parse_link
from ..toc import clean_text, slugify

#: ``(目标, 锚点) -> (href, 是否红链)``
ResolveFn = Callable[[str, str | None], "tuple[str, bool]"]


def default_resolver(target: str, anchor: str | None = None) -> tuple[str, bool]:
    """默认把 ``[[X]]`` 当成同目录下的 ``X.html``，永不算红链。"""
    href = f"{target}.html" + (f"#{anchor}" if anchor else "")
    return href, False


def build_anchor(link: WikiLink, env: dict) -> str:
    """把一个链接渲染成 ``<a>``；红链带 ``.broken`` 与提示。"""
    resolver: ResolveFn = env.get("resolve") or default_resolver
    href, broken = resolver(link.target, link.anchor)
    label = link.label or link.target
    classes = "wikilink broken" if broken else "wikilink"
    title = f' title="页面未创建：{escape(link.target)}"' if broken else ""
    return (
        f'<a class="{classes}" href="{escape(href, quote=True)}"{title}>'
        f"{escape(label)}</a>"
    )


# --- 行内规则 -------------------------------------------------------------
def _wikilink_rule(state, silent: bool) -> bool:
    src = state.src
    pos = state.pos
    if pos + 1 >= state.posMax or src[pos] != "[" or src[pos + 1] != "[":
        return False
    end = src.find("]]", pos + 2)
    if end < 0:
        return False
    inner = src[pos + 2 : end]
    if not inner or "[" in inner or "\n" in inner:
        return False
    if parse_link(f"[[{inner}]]") is None:
        return False
    if not silent:
        token = state.push("wikilink", "", 0)
        token.content = inner
    state.pos = end + 2
    return True


def _render_wikilink(tokens: list[Token], idx: int, options: dict, env: dict) -> str:
    token = tokens[idx]
    link = parse_link(f"[[{token.content}]]")
    if link is None:  # pragma: no cover - 解析阶段已校验
        return escape(token.content)
    return build_anchor(link, env)


def _render_heading_open(tokens: list[Token], idx: int, options: dict, env: dict) -> str:
    token = tokens[idx]
    text = clean_text(tokens[idx + 1].content) if idx + 1 < len(tokens) else ""
    seen: dict[str, int] = env.setdefault("anchors", {})
    base = slugify(text)
    count = seen.get(base, 0) + 1
    seen[base] = count
    anchor = base if count == 1 else f"{base}-{count}"
    level = token.tag[1:] if len(token.tag) > 1 else "2"
    return (
        f'<h{level} id="{escape(anchor)}" class="wiki-heading" '
        f'data-level="{level}">'
    )


def build_markdown(*, allow_html: bool = False) -> MarkdownIt:
    """构造渲染器。每次渲染请用独立的 ``env``，锚点计数依赖它。"""
    md = MarkdownIt(
        "commonmark",
        {"html": allow_html, "linkify": False, "typographer": False},
    )
    md.enable("table")
    md.enable("strikethrough")

    from mdit_py_plugins.dollarmath import dollarmath_plugin
    from mdit_py_plugins.footnote import footnote_plugin

    md.use(dollarmath_plugin)
    md.use(footnote_plugin)

    md.inline.ruler.before("link", "wikilink", _wikilink_rule)
    md.renderer.rules["wikilink"] = _render_wikilink
    md.renderer.rules["heading_open"] = _render_heading_open
    return md


# --- 纯文本模式 -----------------------------------------------------------
def render_text(text: str, env: dict | None = None) -> str:
    """``text`` 模式：只有段落、行内链接与转义，其余字符一律按字面。"""
    context = env if env is not None else {"anchors": {}}
    blocks: list[list[str]] = []
    current: list[str] = []
    for raw in text.splitlines():
        line = S.unescape_line(raw)
        if not line.strip():
            if current:
                blocks.append(current)
                current = []
            continue
        current.append(line)
    if current:
        blocks.append(current)

    rendered: list[str] = []
    for block in blocks:
        body = "<br>\n".join(_escape_with_links(line, context) for line in block)
        rendered.append(f"<p>{body}</p>")
    return "\n".join(rendered)


def _escape_with_links(line: str, env: dict) -> str:
    pieces: list[str] = []
    cursor = 0
    for match in LINK_RE.finditer(line):
        pieces.append(escape(line[cursor : match.start()]))
        link = parse_link(match.group(0))
        if link is None:
            pieces.append(escape(match.group(0)))
        else:
            pieces.append(build_anchor(link, env))
        cursor = match.end()
    pieces.append(escape(line[cursor:]))
    return "".join(pieces)


def render_inline(text: str, env: dict | None = None, *, md: MarkdownIt | None = None) -> str:
    """渲染一段行内 markdown（信息框的值用）。多行会用 ``<br>`` 连接。"""
    context = env if env is not None else {"anchors": {}}
    engine = md or build_markdown()
    lines = text.split("\n")
    return "<br>\n".join(engine.renderInline(line, context) for line in lines)
