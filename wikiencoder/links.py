"""``[[wikilink]]`` 语法。

支持：``[[目标]]``、``[[目标|显示文字]]``、``[[目标#锚点]]``、``[[目标#锚点|显示]]``，
以及预留的嵌入形式 ``![[目标]]``（解析但不特殊渲染）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

LINK_RE = re.compile(
    r"(?<!\\)(?P<embed>!?)\[\["
    r"(?P<target>[^\[\]|#]+?)"
    r"(?:#(?P<anchor>[^\[\]|]+?))?"
    r"(?:\|(?P<label>[^\[\]]+?))?"
    r"\]\]"
)


@dataclass(frozen=True, slots=True)
class WikiLink:
    """一处行内链接。"""

    target: str
    anchor: str | None = None
    label: str | None = None
    embed: bool = False
    line: int = 0
    section: str = ""

    @property
    def display(self) -> str:
        return self.label or self.target

    @property
    def raw(self) -> str:
        text = ("!" if self.embed else "") + "[[" + self.target
        if self.anchor:
            text += "#" + self.anchor
        if self.label:
            text += "|" + self.label
        return text + "]]"


def _build(match: re.Match[str], *, line: int = 0, section: str = "") -> WikiLink:
    return WikiLink(
        target=match.group("target").strip(),
        anchor=(match.group("anchor") or "").strip() or None,
        label=(match.group("label") or "").strip() or None,
        embed=bool(match.group("embed")),
        line=line,
        section=section,
    )


def extract_links(text: str, *, base_line: int = 1, section: str = "") -> list[WikiLink]:
    """抽出文本里所有链接（按出现顺序，带行号）。"""
    links: list[WikiLink] = []
    for offset, raw in enumerate(text.splitlines()):
        for match in LINK_RE.finditer(raw):
            links.append(_build(match, line=base_line + offset, section=section))
    return links


def parse_link(text: str) -> WikiLink | None:
    """整段文本恰好是一个链接时返回它。"""
    match = LINK_RE.fullmatch(text.strip())
    return _build(match) if match else None


def link_text(link: WikiLink) -> str:
    """生成规范写法的链接标记。"""
    return link.raw
