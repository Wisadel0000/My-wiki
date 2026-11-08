"""标识信息框：``键: 值`` 逐行解析（全角冒号也认，缩进行是上一条的续行）。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import E_INFOBOX_LINE, Diagnostic

_SEP = re.compile(r"[ \t]*[:：][ \t]*")


@dataclass(frozen=True, slots=True)
class InfoboxField:
    """信息框的一行。``value`` 可能含换行（续行）。"""

    key: str
    value: str
    line: int = 0


def parse_infobox(
    body: str, *, base_line: int = 1
) -> tuple[list[InfoboxField], list[Diagnostic]]:
    """解析信息框正文。"""
    fields: list[InfoboxField] = []
    diagnostics: list[Diagnostic] = []

    for offset, raw in enumerate(body.splitlines()):
        line = raw.rstrip()
        lineno = base_line + offset
        if not line.strip():
            continue
        if line[0] in " \t" and fields:
            previous = fields[-1]
            fields[-1] = InfoboxField(
                previous.key, f"{previous.value}\n{line.strip()}", previous.line
            )
            continue
        match = _SEP.search(line)
        if match is None or not line[: match.start()].strip():
            diagnostics.append(
                Diagnostic(
                    E_INFOBOX_LINE,
                    f"信息框行缺少「键: 值」格式，已忽略：{line.strip()!r}",
                    lineno,
                    "warn",
                )
            )
            continue
        key = line[: match.start()].strip()
        value = line[match.end() :].strip()
        fields.append(InfoboxField(key, value, lineno))

    return fields, diagnostics


def format_infobox(
    fields: list[tuple[str, str]] | list[InfoboxField], newline: str = "\n"
) -> str:
    """把 ``(键, 值)`` 序列渲染回信息框正文。"""
    lines: list[str] = []
    for field in fields:
        if isinstance(field, InfoboxField):
            key, value = field.key, field.value
        else:
            key, value = field
        value = value.strip()
        if "\n" in value:
            head, *rest = value.split("\n")
            lines.append(f"{key}: {head.strip()}")
            lines.extend(f"  {part.strip()}" for part in rest if part.strip())
        else:
            lines.append(f"{key}: {value}")
    return "".join(line + newline for line in lines)
