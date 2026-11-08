"""参见 / 知识来源 的逐行解析。

这两块是"列表型"板块：``- [[目标]] —— 注解`` / ``书: 书名``。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .links import parse_link

_ITEM = re.compile(r"^[ \t]*(?:[-*+]|[0-9]+[.)])[ \t]+(?P<rest>.+?)[ \t]*$")
#: 注解分隔符（ASCII 冒号不参与，避免把 https:// 切断）
_NOTE_SEPS = ("——", "—", "：")
_KIND = re.compile(
    r"^(?P<kind>书|书籍|图书|专著|网址|链接|网页|URL|url|论文|文章|视频|课程|音频|标准|专利|访谈|笔记)"
    r"[：:][ \t]*(?P<text>.+)$"
)
_URL = re.compile(r"https?://[^\s)）\]】，。；]+")


@dataclass(frozen=True, slots=True)
class SeeAlsoItem:
    """参见里的一条。"""

    raw: str
    target: str = ""
    anchor: str | None = None
    label: str | None = None
    note: str = ""
    line: int = 0

    @property
    def is_link(self) -> bool:
        return bool(self.target)


@dataclass(frozen=True, slots=True)
class SourceItem:
    """知识来源里的一条。"""

    kind: str | None
    text: str
    url: str | None = None
    line: int = 0


def _split_note(text: str) -> tuple[str, str]:
    """在 ``[[...]]`` 之外找第一个注解分隔符。"""
    depth = 0
    i = 0
    while i < len(text):
        if text.startswith("[[", i):
            depth += 1
            i += 2
            continue
        if text.startswith("]]", i) and depth:
            depth -= 1
            i += 2
            continue
        if depth == 0:
            for sep in _NOTE_SEPS:
                if text.startswith(sep, i):
                    head = text[:i].strip()
                    note = text[i + len(sep) :].strip()
                    if head and note:
                        return head, note
        i += 1
    return text.strip(), ""


def parse_seealso(body: str, *, base_line: int = 1) -> list[SeeAlsoItem]:
    """解析参见正文（没有列表符号的行也接受）。"""
    items: list[SeeAlsoItem] = []
    for offset, raw in enumerate(body.splitlines()):
        line = raw.rstrip()
        if not line.strip():
            continue
        match = _ITEM.match(line)
        rest = match.group("rest").strip() if match else line.strip()
        head, note = _split_note(rest)
        link = parse_link(head)
        items.append(
            SeeAlsoItem(
                raw=line.strip(),
                target=link.target if link else head,
                anchor=link.anchor if link else None,
                label=link.label if link else None,
                note=note,
                line=base_line + offset,
            )
        )
    return items


def parse_sources(body: str, *, base_line: int = 1) -> list[SourceItem]:
    """解析知识来源正文。"""
    items: list[SourceItem] = []
    for offset, raw in enumerate(body.splitlines()):
        line = raw.rstrip()
        if not line.strip():
            continue
        match = _ITEM.match(line)
        rest = match.group("rest").strip() if match else line.strip()
        kind: str | None = None
        text = rest
        kind_match = _KIND.match(rest)
        if kind_match:
            kind = kind_match.group("kind")
            text = kind_match.group("text").strip()
        url_match = _URL.search(text)
        items.append(
            SourceItem(
                kind=kind,
                text=text,
                url=url_match.group(0) if url_match else None,
                line=base_line + offset,
            )
        )
    return items
