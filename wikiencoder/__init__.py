"""WikiEncoder —— 纯文本 wiki 框架。

设计要点：
- 一页一文件（``<slug>.wiki``），UTF-8 + LF；
- 文件里只有"事实"：章节正文、信息框键值、编辑记录表格；
- 目录、总修改次数、反向链接等一律派生，绝不落盘；
- 解析 → 序列化 **逐字节无损**，未修改的部分一个字节都不动。

语法规范见 ``docs/SYNTAX.md``。
"""

from __future__ import annotations

from .editor import Editor
from .errors import Diagnostic, ParseError, WikiError
from .model import (
    EditRecord,
    FrontMatter,
    InfoboxField,
    Section,
    SeeAlsoItem,
    SourceItem,
    WikiPage,
)
from .parser import parse, parse_file
from .render import RenderedPage, render_body, render_fragment, render_page, render_parts
from .serializer import canonicalize, serialize
from .store import OpResult, WikiStore
from .syntax import FORMAT_VERSION

__version__ = "0.1.0.dev0"

__all__ = [
    "FORMAT_VERSION",
    "Diagnostic",
    "EditRecord",
    "Editor",
    "FrontMatter",
    "InfoboxField",
    "OpResult",
    "ParseError",
    "RenderedPage",
    "Section",
    "SeeAlsoItem",
    "SourceItem",
    "WikiError",
    "WikiPage",
    "WikiStore",
    "__version__",
    "canonicalize",
    "parse",
    "parse_file",
    "render_body",
    "render_fragment",
    "render_page",
    "render_parts",
    "serialize",
]
