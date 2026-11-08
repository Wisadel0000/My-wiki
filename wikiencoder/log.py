"""编辑记录：markdown 表格的解析与生成。

表结构固定为「表头 + 分隔行 + 数据行」，列按表头文字识别，
缺列时回落到位置顺序 ``# / 日期 / 作者 / 说明``。
总修改次数由行数派生，不额外存储。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import E_LOG_TABLE, Diagnostic

_ROW = re.compile(r"^[ \t]*\|(?P<row>.*)\|[ \t]*$")
_SEP_CELL = re.compile(r"^[ \t]*:?-{2,}:?[ \t]*$")

COLUMNS = ("n", "date", "author", "message")

_HEADER_ALIASES: dict[str, str] = {
    "#": "n",
    "no": "n",
    "编号": "n",
    "序号": "n",
    "次": "n",
    "次数": "n",
    "日期": "date",
    "时间": "date",
    "date": "date",
    "作者": "author",
    "编辑者": "author",
    "修改者": "author",
    "author": "author",
    "说明": "message",
    "修改说明": "message",
    "提交信息": "message",
    "描述": "message",
    "备注": "message",
    "内容": "message",
    "message": "message",
    "log": "message",
}


@dataclass(frozen=True, slots=True)
class EditRecord:
    """一条编辑记录。"""

    n: int
    date: str = ""
    author: str = ""
    message: str = ""
    line: int = 0


def _cells(line: str) -> list[str] | None:
    match = _ROW.match(line)
    if not match:
        return None
    return [cell.strip() for cell in match.group("row").split("|")]


def _column_map(header: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for index, cell in enumerate(header):
        key = _HEADER_ALIASES.get(cell.strip()) or _HEADER_ALIASES.get(cell.strip().lower())
        if key and key not in mapping:
            mapping[key] = index
    for index, key in enumerate(COLUMNS):
        mapping.setdefault(key, index)
    return mapping


def _cell(cells: list[str], mapping: dict[str, int], key: str) -> str:
    index = mapping[key]
    return cells[index] if index < len(cells) else ""


def parse_log(
    body: str, *, base_line: int = 1
) -> tuple[list[EditRecord], list[Diagnostic]]:
    """解析编辑记录正文。空板块返回空列表。"""
    diagnostics: list[Diagnostic] = []
    rows: list[tuple[int, list[str]]] = []

    for offset, raw in enumerate(body.splitlines()):
        line = raw.rstrip()
        if not line.strip():
            continue
        cells = _cells(line)
        if cells is None:
            diagnostics.append(
                Diagnostic(
                    E_LOG_TABLE,
                    f"编辑记录里出现了非表格行：{line.strip()!r}",
                    base_line + offset,
                    "warn",
                )
            )
            continue
        rows.append((base_line + offset, cells))

    if not rows:
        return [], diagnostics

    header_line, header = rows[0]
    data: list[tuple[int, list[str]]] = []
    if len(rows) > 1 and all(_SEP_CELL.match(cell) for cell in rows[1][1] if cell):
        data = rows[2:]
    else:
        if len(rows) > 1:
            diagnostics.append(
                Diagnostic(
                    E_LOG_TABLE,
                    "编辑记录表格缺少分隔行（|---|）",
                    rows[1][0],
                    "warn",
                )
            )
        data = rows[1:]

    mapping = _column_map(header)
    records: list[EditRecord] = []
    for index, (lineno, cells) in enumerate(data, 1):
        raw_n = _cell(cells, mapping, "n")
        try:
            number = int(re.sub(r"[^0-9]", "", raw_n) or index)
        except ValueError:
            number = index
        records.append(
            EditRecord(
                n=number or index,
                date=_cell(cells, mapping, "date"),
                author=_cell(cells, mapping, "author"),
                message=_cell(cells, mapping, "message"),
                line=lineno,
            )
        )
    _ = header_line
    return records, diagnostics


def format_log(records: list[EditRecord], newline: str = "\n") -> str:
    """把记录渲染成紧凑的 markdown 表格（编号按当前顺序重排）。"""
    lines = ["| # | 日期 | 作者 | 说明 |", "|---|------|------|------|"]
    for index, record in enumerate(records, 1):
        cells = [str(index), record.date, record.author, record.message]
        lines.append("| " + " | ".join(cells) + " |")
    return "".join(line + newline for line in lines)
