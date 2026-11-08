"""WikiPage → 文本。

核心约定：**没改过的部分逐字节照抄原文**。只有被标记为 dirty 的板块
正文 / 指令行才会被重新排版，因此任何编辑都不会污染文件其余部分。
"""

from __future__ import annotations

from . import syntax as S
from .model import Section, WikiPage
from .parser import parse


def serialize(page: WikiPage) -> str:
    """把页面写回文本。"""
    parts: list[str] = [page.bom, _front_text(page), page.prologue_raw]
    last = len(page.sections) - 1
    for index, section in enumerate(page.sections):
        parts.append(_directive_text(section, page.newline))
        parts.append(_body_text(section, page.newline, is_last=index == last))
    return "".join(parts)


def render_frontmatter(fields: dict[str, str], newline: str = "\n") -> str:
    """按给定顺序渲染 front matter 块。"""
    body = "".join(f"{key}: {value}{newline}" for key, value in fields.items())
    return f"{S.FRONTMATTER_FENCE}{newline}{body}{S.FRONTMATTER_FENCE}{newline}"


def _front_text(page: WikiPage) -> str:
    front = page.front
    if front.raw is not None and not front.dirty:
        return front.raw
    if not front.fields:
        return ""
    return render_frontmatter(front.fields, page.newline)


def _directive_text(section: Section, newline: str) -> str:
    if not section.head_dirty and section.directive_raw:
        return section.directive_raw
    return S.format_directive(section.title, section.mode) + newline


def _body_text(section: Section, newline: str, *, is_last: bool) -> str:
    if not section.body_dirty:
        return section.body_raw
    return normalize_body(section.body, newline, is_last=is_last)


def normalize_body(text: str, newline: str = "\n", *, is_last: bool = True) -> str:
    """规范正文：统一 LF、去掉行尾空白行、非末位板块补一个空行分隔。"""
    body = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = body.split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    result = "\n".join(lines)
    if result:
        result += "\n"
    if not is_last:
        result += "\n"
    return result.replace("\n", newline)


def canonicalize(text: str) -> str:
    """把整个文件重排成规范形式（语义不变，可反复执行）。"""
    page = parse(text)
    for section in page.sections:
        section.body_dirty = True
        section.head_dirty = True
        if section.key in S.CANONICAL_TITLES:
            section.title = S.CANONICAL_TITLES[section.key]
    page.front.dirty = bool(page.front.fields)
    return serialize(page)
