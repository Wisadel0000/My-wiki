"""文本 → :class:`WikiPage`。

解析严格但宽容：
- 结构错误（围栏/front matter 没闭合、正文不在任何板块里）→ :class:`ParseError`；
- 语义问题（未知板块、重复板块、缩进不对）→ 收进 ``page.diagnostics``，绝不丢内容。
"""

from __future__ import annotations

from pathlib import Path

from . import syntax as S
from .errors import (
    E_ENCODING,
    E_FENCE_UNCLOSED,
    E_FRONT_UNCLOSED,
    E_META_LINE,
    I_IMPLICIT_PREAMBLE,
    W_DUPLICATE_SECTION,
    W_UNKNOWN_SECTION,
    Diagnostic,
    ParseError,
)
from .model import FrontMatter, Section, WikiPage


def _is_front_fence(line: str) -> bool:
    return line.rstrip("\r\n").strip() == S.FRONTMATTER_FENCE


def _parse_front_fields(
    text: str, *, base_line: int = 1
) -> tuple[dict[str, str], list[Diagnostic]]:
    fields: dict[str, str] = {}
    diagnostics: list[Diagnostic] = []
    for offset, raw in enumerate(text.splitlines()):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            diagnostics.append(
                Diagnostic(
                    E_META_LINE,
                    f"front matter 行缺少冒号：{line!r}",
                    base_line + offset,
                    "warn",
                )
            )
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip()
    return fields, diagnostics


def parse(text: str, *, path: Path | None = None) -> WikiPage:
    """把一份 wiki 文本解析成 :class:`WikiPage`。"""
    diagnostics: list[Diagnostic] = []

    bom = ""
    if text.startswith("\ufeff"):
        bom = "\ufeff"
        text = text[1:]

    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    total = len(lines)
    pos = 0

    front = FrontMatter()
    if total and _is_front_fence(lines[0]):
        close = next((j for j in range(1, total) if _is_front_fence(lines[j])), None)
        if close is None:
            raise ParseError(E_FRONT_UNCLOSED, "front matter 缺少闭合的 --- 行", 1)
        front.raw = "".join(lines[0 : close + 1])
        front.fields, front_diagnostics = _parse_front_fields(
            "".join(lines[1:close]), base_line=2
        )
        diagnostics.extend(front_diagnostics)
        pos = close + 1

    prologue_start = pos
    while pos < total and not S.is_directive_line(lines[pos]):
        pos += 1
    prologue = "".join(lines[prologue_start:pos])
    if prologue.strip() and pos < total:
        diagnostics.append(
            Diagnostic(
                I_IMPLICIT_PREAMBLE,
                "首个 @ 之前的正文被当作序言；建议显式写成「@ 序言」",
                prologue_start + 1,
                "info",
            )
        )

    sections: list[Section] = []
    seen: dict[str, int] = {}

    while pos < total:
        directive = lines[pos]
        title, mode = S.split_directive(directive)
        line_no = pos + 1
        pos += 1

        body_start = pos
        fence: str | None = None
        fence_line = 0
        while pos < total:
            bare = lines[pos].rstrip("\r\n")
            if not bare.startswith("\\"):
                if fence is None:
                    if S.is_directive_line(lines[pos]):
                        break
                    opened = S.FENCE_OPEN.match(bare)
                    if opened:
                        fence = opened.group("fence")
                        fence_line = pos + 1
                else:
                    closed = S.FENCE_CLOSE.match(bare)
                    if closed and len(closed.group("fence")) == len(fence):
                        fence = None
            pos += 1
        if fence is not None:
            raise ParseError(E_FENCE_UNCLOSED, f"围栏 {fence} 没有闭合", fence_line)

        key = S.resolve_section(title)
        if key is None:
            key = S.EXTRA
            diagnostics.append(
                Diagnostic(
                    W_UNKNOWN_SECTION,
                    f"未知板块「{title}」，按自定义板块保留",
                    line_no,
                    "warn",
                )
            )
        else:
            seen[key] = seen.get(key, 0) + 1
            if seen[key] > 1:
                diagnostics.append(
                    Diagnostic(
                        W_DUPLICATE_SECTION,
                        f"板块「{S.CANONICAL_TITLES[key]}」重复出现（以第一个为准）",
                        line_no,
                        "warn",
                    )
                )

        body_raw = "".join(lines[body_start:pos])
        sections.append(
            Section(
                key=key,
                title=title,
                body=body_raw,
                body_raw=body_raw,
                directive_raw=directive,
                mode=mode,
                line=line_no,
            )
        )

    slug = front.get("slug") or (path.stem if path else "")
    return WikiPage(
        slug=slug,
        front=front,
        sections=sections,
        prologue_raw=prologue,
        bom=bom,
        newline=newline,
        path=path,
        diagnostics=diagnostics,
    )


def parse_file(path: str | Path) -> WikiPage:
    """读文件并解析（UTF-8，自动保留 BOM）。"""
    target = Path(path)
    try:
        text = target.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ParseError(E_ENCODING, f"文件不是合法 UTF-8：{exc}", 0) from exc
    return parse(text, path=target)
