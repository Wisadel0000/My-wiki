"""语法常量与行级扫描。

这一层只负责"识别"，不解释任何板块语义：
``@`` 指令行、``:::` 围栏、转义、板块名别名。
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

from .errors import E_FENCE_UNCLOSED, ParseError

FORMAT_VERSION = 1
FRONTMATTER_FENCE = "---"

# --- 板块规范 key ---------------------------------------------------------
PREAMBLE = "preamble"
INFOBOX = "infobox"
TOC = "toc"
BODY = "body"
SEEALSO = "seealso"
SOURCES = "sources"
LOG = "log"
EXTRA = "extra"

CANONICAL_ORDER: tuple[str, ...] = (PREAMBLE, INFOBOX, TOC, BODY, SEEALSO, SOURCES, LOG)

CANONICAL_TITLES: dict[str, str] = {
    PREAMBLE: "序言",
    INFOBOX: "标识信息框",
    TOC: "目录",
    BODY: "详细内容",
    SEEALSO: "参见",
    SOURCES: "知识来源",
    LOG: "编辑记录",
}

_ALIASES: dict[str, str] = {
    # 序言 / 定义
    "序言": PREAMBLE,
    "序": PREAMBLE,
    "定义": PREAMBLE,
    "引言": PREAMBLE,
    "概述": PREAMBLE,
    "摘要": PREAMBLE,
    "preamble": PREAMBLE,
    # 标识信息框
    "标识信息框": INFOBOX,
    "信息框": INFOBOX,
    "信息栏": INFOBOX,
    "基本资料": INFOBOX,
    "标识": INFOBOX,
    "infobox": INFOBOX,
    # 目录
    "目录": TOC,
    "目次": TOC,
    "toc": TOC,
    # 详细内容
    "详细内容": BODY,
    "详细介绍": BODY,
    "正文": BODY,
    "正文内容": BODY,
    "内容": BODY,
    "body": BODY,
    # 参见
    "参见": SEEALSO,
    "参见条目": SEEALSO,
    "相关条目": SEEALSO,
    "另见": SEEALSO,
    "相关": SEEALSO,
    "seealso": SEEALSO,
    "see also": SEEALSO,
    # 知识来源
    "知识来源": SOURCES,
    "来源": SOURCES,
    "参考资料": SOURCES,
    "参考文献": SOURCES,
    "参考": SOURCES,
    "sources": SOURCES,
    # 编辑记录
    "编辑记录": LOG,
    "修改记录": LOG,
    "变更记录": LOG,
    "变更日志": LOG,
    "log": LOG,
}

#: 各板块正文的默认渲染模式；可在指令后写 ``{md}`` / ``{text}`` 覆盖
DEFAULT_MODES: dict[str, str] = {
    PREAMBLE: "md",
    INFOBOX: "text",
    TOC: "text",
    BODY: "md",
    SEEALSO: "text",
    SOURCES: "text",
    LOG: "text",
}

MODES = ("md", "text")


def resolve_section(name: str) -> str | None:
    """把文件里写的板块名解析成规范 key；未知返回 ``None``。"""
    key = name.strip()
    if key in _ALIASES:
        return _ALIASES[key]
    return _ALIASES.get(key.lower())


# --- 指令行 ---------------------------------------------------------------
_DIRECTIVE = re.compile(r"^@[ \t]*(?P<rest>[^\s].*?)[ \t]*$")
_MODE_SUFFIX = re.compile(r"^(?P<name>.+?)[ \t]*\{[ \t]*(?P<mode>md|text)[ \t]*\}$")


def is_directive_line(line: str) -> bool:
    """判断一整行（可带换行符）是不是板块指令。"""
    bare = line.rstrip("\r\n")
    if not bare or not bare.startswith("@"):
        return False
    if bare.startswith("@@"):  # ``@@`` 不是指令，避免吃掉常见的 @ 行
        return False
    return bool(_DIRECTIVE.match(bare))


def split_directive(line: str) -> tuple[str, str | None]:
    """拆出 ``(板块名, 模式覆盖)``；不是指令则抛 ``ValueError``。"""
    m = _DIRECTIVE.match(line.rstrip("\r\n"))
    if not m:
        raise ValueError(f"不是合法的板块指令行: {line!r}")
    rest = m.group("rest").strip()
    mm = _MODE_SUFFIX.match(rest)
    if mm:
        return mm.group("name").strip(), mm.group("mode")
    return rest, None


def format_directive(title: str, mode: str | None = None) -> str:
    """生成规范写法的指令行（不含换行符）。"""
    t = title.strip()
    return f"@ {t} {{{mode}}}" if mode else f"@ {t}"


# --- 围栏 -----------------------------------------------------------------
#: 开启围栏必须带模式词：``::: md`` / ``::: text``；裸 ``:::`` 一律视为闭合。
FENCE_OPEN = re.compile(r"^(?P<fence>:{3,})[ \t]+(?P<mode>md|text)[ \t]*$")
FENCE_CLOSE = re.compile(r"^(?P<fence>:{3,})[ \t]*$")


@dataclass(frozen=True, slots=True)
class Region:
    """一段同模式的正文。"""

    mode: str
    text: str
    line: int  # 1-based 起始行号


def iter_regions(body: str, default_mode: str, *, base_line: int = 1) -> Iterator[Region]:
    """按 ``:::`` 围栏把正文切成若干区域，围栏行本身不进入内容。"""
    lines = body.splitlines(keepends=True)
    mode = default_mode
    fence: str | None = None
    fence_line = 0
    buf: list[str] = []
    buf_line = base_line

    for offset, line in enumerate(lines):
        lineno = base_line + offset
        bare = line.rstrip("\r\n")
        escaped = bare.startswith("\\")

        if fence is None:
            opened = FENCE_OPEN.match(bare) if not escaped else None
            if opened:
                if buf:
                    yield Region(mode, "".join(buf), buf_line)
                    buf = []
                fence = opened.group("fence")
                fence_line = lineno
                mode = opened.group("mode")
                buf_line = lineno + 1
                continue
            if not buf:
                buf_line = lineno
            buf.append(line)
        else:
            closed = FENCE_CLOSE.match(bare) if not escaped else None
            if closed and len(closed.group("fence")) == len(fence):
                if buf:
                    yield Region(mode, "".join(buf), buf_line)
                buf = []
                fence = None
                mode = default_mode
                buf_line = lineno + 1
                continue
            buf.append(line)

    if fence is not None:
        raise ParseError(E_FENCE_UNCLOSED, f"围栏 {fence} 没有闭合", fence_line)
    if buf:
        yield Region(mode, "".join(buf), buf_line)


# --- 转义 -----------------------------------------------------------------
_ESCAPABLE = ("@", ":::", "[[")


def unescape_line(line: str) -> str:
    """去掉行首的结构性转义（用于渲染）。"""
    if line.startswith("\\"):
        for prefix in _ESCAPABLE:
            if line.startswith("\\" + prefix):
                return line[1:]
    return line


def escape_line(line: str) -> str:
    """给行首可能被误认成结构的文本加转义（用于写入）。"""
    for prefix in ("@", ":::"):
        if line.startswith(prefix):
            return "\\" + line
    return line
