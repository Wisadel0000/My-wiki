"""数据结构：front matter、板块、页面。

约定：``*_raw`` 字段保存文件里的原始字节（含换行），用于无损序列化；
不带 ``raw`` 的字段是可编辑的"活数据"。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import syntax as S
from .blocks import SeeAlsoItem, SourceItem, parse_seealso, parse_sources
from .errors import Diagnostic
from .infobox import InfoboxField, parse_infobox
from .links import WikiLink, extract_links
from .log import EditRecord, parse_log
from .toc import Heading, iter_headings

#: 值按逗号切成列表的元数据字段
LIST_FIELDS = ("aliases", "tags")

_LIST_SPLIT = ("\uff0c", "\u3001", ",")  # ，、,


def split_list(value: str) -> list[str]:
    """把 ``"a, b、c"`` 切成 ``["a", "b", "c"]``。"""
    out: list[str] = []
    buf = value
    for sep in _LIST_SPLIT:
        buf = buf.replace(sep, "\x00")
    for part in buf.split("\x00"):
        item = part.strip()
        if item:
            out.append(item)
    return out


@dataclass
class FrontMatter:
    """``---`` 包裹的扁平元数据。保持插入顺序。"""

    fields: dict[str, str] = field(default_factory=dict)
    raw: str | None = None  # 原文（含首尾 --- 行与其换行）；None = 文件里没有
    dirty: bool = False

    def get(self, key: str, default: str = "") -> str:
        return self.fields.get(key, default)

    def get_list(self, key: str) -> list[str]:
        return split_list(self.fields.get(key, ""))

    def set(self, key: str, value: str) -> None:
        self.fields[key] = value
        self.dirty = True

    def set_list(self, key: str, values: list[str]) -> None:
        self.fields[key] = ", ".join(v.strip() for v in values if v.strip())
        self.dirty = True

    def __contains__(self, key: object) -> bool:
        return key in self.fields


@dataclass
class Section:
    """一个 ``@ 板块`` 及其正文。"""

    key: str  # 规范 key（S.PREAMBLE…）或 S.EXTRA
    title: str  # 文件里写的原标题
    body: str = ""  # 活数据（编辑后与 body_raw 可能不同）
    body_raw: str = ""  # 原文
    directive_raw: str = ""  # 原始指令行（含换行）
    mode: str | None = None  # 显式模式覆盖；None = 用默认
    body_dirty: bool = False
    head_dirty: bool = False
    line: int = 0  # 1-based 指令行号

    # --- 视图 ---
    @property
    def is_extra(self) -> bool:
        return self.key == S.EXTRA

    @property
    def effective_mode(self) -> str:
        return self.mode or S.DEFAULT_MODES.get(self.key, "md")

    @property
    def is_empty(self) -> bool:
        return not self.body.strip()

    @property
    def name(self) -> str:
        return S.CANONICAL_TITLES.get(self.key, self.title)

    # --- 编辑 ---
    def set_body(self, text: str) -> Section:
        self.body = text if text.endswith("\n") or not text else text + "\n"
        self.body_dirty = True
        return self

    def append(self, text: str) -> Section:
        cur = self.body
        if cur and not cur.endswith("\n"):
            cur += "\n"
        self.body = cur + text
        self.body_dirty = True
        return self

    def prepend(self, text: str) -> Section:
        self.body = text + self.body
        self.body_dirty = True
        return self

    def set_mode(self, mode: str | None) -> Section:
        if mode is not None and mode not in S.MODES:
            raise ValueError(f"未知模式: {mode!r}")
        self.mode = mode
        self.head_dirty = True
        return self

    def __str__(self) -> str:
        return f"<Section {self.key} {self.title!r} lines={self.line}>"


@dataclass
class WikiPage:
    """一个 wiki 页面。"""

    slug: str = ""
    front: FrontMatter = field(default_factory=FrontMatter)
    sections: list[Section] = field(default_factory=list)
    prologue_raw: str = ""  # 首个 @ 之前的正文（隐式序言）
    bom: str = ""
    newline: str = "\n"
    path: Path | None = None
    diagnostics: list[Diagnostic] = field(default_factory=list)

    # --- 元数据 ---
    @property
    def title(self) -> str:
        return self.front.get("title") or self.slug

    @title.setter
    def title(self, value: str) -> None:
        self.front.set("title", value)

    @property
    def kind(self) -> str:
        """对应 front matter 的 ``type``（概念/定理/方法…）。"""
        return self.front.get("type")

    @kind.setter
    def kind(self, value: str) -> None:
        self.front.set("type", value)

    @property
    def aliases(self) -> list[str]:
        return self.front.get_list("aliases")

    @property
    def tags(self) -> list[str]:
        return self.front.get_list("tags")

    @tags.setter
    def tags(self, values: list[str]) -> None:
        self.front.set_list("tags", values)

    @property
    def created(self) -> str:
        return self.front.get("created")

    @property
    def meta(self) -> dict[str, str]:
        return self.front.fields

    # --- 板块 ---
    def get_section(self, name: str) -> Section | None:
        """按规范 key、别名或自定义板块标题取板块。"""
        key = S.resolve_section(name)
        if key is not None:
            return next((s for s in self.sections if s.key == key), None)
        want = name.strip()
        return next((s for s in self.sections if s.is_extra and s.title.strip() == want), None)

    def has_section(self, name: str) -> bool:
        return self.get_section(name) is not None

    def section_keys(self) -> list[str]:
        return [s.key for s in self.sections]

    def extras(self) -> list[Section]:
        return [s for s in self.sections if s.is_extra]

    def insert_section(self, section: Section, index: int | None = None) -> Section:
        """插入板块（默认追加）。会把前一个板块标记为需要规范化，

        这样"未改动过的旧板块"和新板块之间才会补上分隔空行。
        """
        if index is None:
            index = len(self.sections)
        self.sections.insert(index, section)
        if index > 0:
            self.sections[index - 1].body_dirty = True
        return section

    def ensure_section(self, key: str) -> Section:
        """取板块，没有就按规范顺序插入一个空的。"""
        existing = self.get_section(key)
        if existing is not None:
            return existing
        title = S.CANONICAL_TITLES.get(key, key)
        section = Section(key=key, title=title, head_dirty=True)
        rank = S.CANONICAL_ORDER.index(key) if key in S.CANONICAL_ORDER else len(S.CANONICAL_ORDER)
        index = len(self.sections)
        for i, sec in enumerate(self.sections):
            other = (
                S.CANONICAL_ORDER.index(sec.key)
                if sec.key in S.CANONICAL_ORDER
                else len(S.CANONICAL_ORDER)
            )
            if other > rank:
                index = i
                break
        section.line = 0
        return self.insert_section(section, index)

    @property
    def preamble(self) -> str:
        """序言正文；没有 ``@ 序言`` 时回落到首个指令之前的正文。"""
        section = self.get_section(S.PREAMBLE)
        return section.body if section is not None else self.prologue_raw

    # --- 派生结构（全部现算，不缓存、不落盘） ---
    def infobox_fields(self) -> list[InfoboxField]:
        section = self.get_section(S.INFOBOX)
        if section is None:
            return []
        return parse_infobox(section.body, base_line=section.line + 1)[0]

    def infobox_dict(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for item in self.infobox_fields():
            out[item.key] = item.value
        return out

    def edit_records(self) -> list[EditRecord]:
        section = self.get_section(S.LOG)
        if section is None:
            return []
        return parse_log(section.body, base_line=section.line + 1)[0]

    def seealso_items(self) -> list[SeeAlsoItem]:
        section = self.get_section(S.SEEALSO)
        if section is None:
            return []
        return parse_seealso(section.body, base_line=section.line + 1)

    def source_items(self) -> list[SourceItem]:
        section = self.get_section(S.SOURCES)
        if section is None:
            return []
        return parse_sources(section.body, base_line=section.line + 1)

    def headings(self) -> list[Heading]:
        """正文与自定义板块里的多级标题（用于生成目录）。"""
        out: list[Heading] = []
        seen: dict[str, int] = {}
        for section in self.sections:
            if section.key in (S.BODY, S.EXTRA):
                out.extend(
                    iter_headings(
                        section.body,
                        section.effective_mode,
                        base_line=section.line + 1,
                        seen=seen,
                    )
                )
        return out

    def links(self) -> list[WikiLink]:
        """本页所有 ``[[链接]]``（含信息框、参见里的）。"""
        out: list[WikiLink] = []
        for section in self.sections:
            out.extend(
                extract_links(
                    section.body, base_line=section.line + 1, section=section.key
                )
            )
        return out

    # --- 序列化 ---
    def to_text(self) -> str:
        from .serializer import serialize

        return serialize(self)

    def __str__(self) -> str:
        return self.to_text()
