"""多级标题解析与锚点生成（目录、跨页锚点校验都靠它）。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import syntax as S
from .links import LINK_RE

_HEADING = re.compile(r"^(?P<hashes>#{1,6})[ \t]+(?P<text>.+?)[ \t]*$")
_TRAILING_HASHES = re.compile(r"[ \t]+#+$")
_INLINE_NOISE = re.compile(r"[*_`~]")


@dataclass(frozen=True, slots=True)
class Heading:
    """一个标题。``anchor`` 是 HTML 里的 ``id``。"""

    level: int
    text: str
    anchor: str
    line: int = 0


def clean_text(text: str) -> str:
    """去掉行内标记，得到可读的标题文字。"""
    cleaned = LINK_RE.sub(lambda m: (m.group("label") or m.group("target")), text)
    cleaned = _INLINE_NOISE.sub("", cleaned)
    cleaned = _TRAILING_HASHES.sub("", cleaned)
    return cleaned.strip()


def slugify(text: str) -> str:
    """中文保留、空白转连字符、其余标点丢弃。"""
    slug = re.sub(r"\s+", "-", text.strip())
    slug = re.sub(r"[^\w\u4e00-\u9fff\-]", "", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or "section"


def iter_headings(
    body: str,
    mode: str,
    *,
    base_line: int = 1,
    seen: dict[str, int] | None = None,
) -> list[Heading]:
    """按区域模式下解析标题：``text`` 区域里的 ``#`` 不算标题。

    ``seen`` 用于跨板块共享锚点计数，保证与正文渲染出来的 ``id`` 完全一致。
    """
    headings: list[Heading] = []
    seen = {} if seen is None else seen

    for region in S.iter_regions(body, mode, base_line=base_line):
        if region.mode != "md":
            continue
        for offset, raw in enumerate(region.text.splitlines()):
            match = _HEADING.match(raw.rstrip())
            if not match:
                continue
            text = clean_text(match.group("text"))
            if not text:
                continue
            base = slugify(text)
            count = seen.get(base, 0) + 1
            seen[base] = count
            anchor = base if count == 1 else f"{base}-{count}"
            headings.append(
                Heading(
                    level=len(match.group("hashes")),
                    text=text,
                    anchor=anchor,
                    line=region.line + offset,
                )
            )
    return headings
