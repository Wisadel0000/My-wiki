"""编辑操作：对内存里的 :class:`WikiPage` 做结构化修改。

约定：
- 每个方法返回 ``bool``（是否真的发生了变化），天然幂等；
- **不碰文件**，落盘由 :class:`wikiencoder.store.WikiStore` 负责；
- 只有 :meth:`Editor.add_edit_record` 会写编辑记录，其它方法一律不动日志；
- 信息框 / 参见 / 来源 / 编辑记录都是有结构的板块，写入时统一按规范重排。
"""

from __future__ import annotations

from datetime import date

from . import syntax as S
from .blocks import parse_seealso
from .infobox import format_infobox, parse_infobox
from .log import EditRecord, format_log, parse_log
from .model import Section, WikiPage


def _clean(text: str) -> str:
    """统一行尾并保证以单个换行结尾。"""
    body = text.replace("\r\n", "\n").replace("\r", "\n")
    return body if body.endswith("\n") else body + "\n"


class Editor:
    """一个页面的编辑会话。"""

    def __init__(
        self, page: WikiPage, *, author: str = "", today: str | None = None
    ) -> None:
        self.page = page
        self.author = author
        self.today = today or date.today().isoformat()
        self.changed = False

    # --- 内部 ---
    def _mark(self, changed: bool) -> bool:
        if changed:
            self.changed = True
        return changed

    def _ensure(self, name: str) -> Section:
        key = S.resolve_section(name)
        if key is not None:
            return self.page.ensure_section(key)
        existing = self.page.get_section(name)
        if existing is not None:
            return existing
        section = Section(key=S.EXTRA, title=name.strip(), head_dirty=True)
        return self.page.insert_section(section)

    # --- 元数据 ---
    def set_title(self, title: str) -> bool:
        if self.page.front.get("title") == title:
            return self._mark(False)
        self.page.title = title
        return self._mark(True)

    def set_kind(self, kind: str) -> bool:
        if self.page.front.get("type") == kind:
            return self._mark(False)
        self.page.kind = kind
        return self._mark(True)

    def add_alias(self, alias: str) -> bool:
        aliases = list(self.page.aliases)
        alias = alias.strip()
        if not alias or alias in aliases:
            return self._mark(False)
        aliases.append(alias)
        self.page.front.set_list("aliases", aliases)
        return self._mark(True)

    # --- 标签 ---
    def set_tags(self, tags: list[str]) -> bool:
        cleaned: list[str] = []
        for tag in tags:
            item = _clean_tag(tag)
            if item and item not in cleaned:
                cleaned.append(item)
        if cleaned == list(self.page.tags):
            return self._mark(False)
        self.page.tags = cleaned
        return self._mark(True)

    def add_tag(self, tag: str) -> bool:
        tag = _clean_tag(tag)
        if not tag or tag in self.page.tags:
            return self._mark(False)
        return self.set_tags([*self.page.tags, tag])

    def remove_tag(self, tag: str) -> bool:
        tag = _clean_tag(tag)
        current = list(self.page.tags)
        if tag not in current:
            return self._mark(False)
        return self.set_tags([item for item in current if item != tag])

    # --- 序言 ---
    def set_preamble(self, text: str) -> bool:
        section = self.page.ensure_section(S.PREAMBLE)
        new = _clean(text)
        if section.body == new:
            return self._mark(False)
        section.set_body(new)
        return self._mark(True)

    def append_preamble(self, text: str) -> bool:
        section = self.page.ensure_section(S.PREAMBLE)
        if text.strip() and _clean(text) in section.body:
            return self._mark(False)
        section.append(_clean(text))
        return self._mark(True)

    # --- 通用板块 ---
    def set_section(self, name: str, text: str) -> bool:
        section = self._ensure(name)
        new = _clean(text)
        if section.body == new:
            return self._mark(False)
        section.set_body(new)
        return self._mark(True)

    def append_section(self, name: str, text: str) -> bool:
        section = self._ensure(name)
        addition = _clean(text)
        body = section.body.rstrip("\n")
        new = f"{body}\n\n{addition}" if body else addition
        if section.body == new:
            return self._mark(False)
        section.set_body(new)
        return self._mark(True)

    def remove_section(self, name: str) -> bool:
        section = self.page.get_section(name)
        if section is None:
            return self._mark(False)
        self.page.sections.remove(section)
        return self._mark(True)

    # --- 信息框 ---
    def _infobox_pairs(self) -> list[tuple[str, str]]:
        section = self.page.get_section(S.INFOBOX)
        if section is None:
            return []
        return [(item.key, item.value) for item in parse_infobox(section.body)[0]]

    def _write_infobox(self, pairs: list[tuple[str, str]]) -> bool:
        section = self.page.ensure_section(S.INFOBOX)
        section.set_body(format_infobox(pairs))
        return self._mark(True)

    def set_infobox(self, key: str, value: str) -> bool:
        key = key.strip()
        value = value.strip()
        pairs = self._infobox_pairs()
        for index, (existing_key, existing_value) in enumerate(pairs):
            if existing_key == key:
                if existing_value == value:
                    return self._mark(False)
                pairs[index] = (key, value)
                return self._write_infobox(pairs)
        pairs.append((key, value))
        return self._write_infobox(pairs)

    def remove_infobox(self, key: str) -> bool:
        pairs = self._infobox_pairs()
        remaining = [pair for pair in pairs if pair[0] != key.strip()]
        if len(remaining) == len(pairs):
            return self._mark(False)
        if not remaining:
            return self.remove_section(S.INFOBOX)
        return self._write_infobox(remaining)

    # --- 参见 ---
    def _seealso_targets(self) -> set[str]:
        section = self.page.get_section(S.SEEALSO)
        if section is None:
            return set()
        return {item.target for item in parse_seealso(section.body)}

    def add_seealso(self, target: str, note: str = "") -> bool:
        target = target.strip()
        if not target or target in self._seealso_targets():
            return self._mark(False)
        line = f"- [[{target}]]"
        if note.strip():
            line += f" —— {note.strip()}"
        return self.append_section(S.SEEALSO, line + "\n")

    def remove_seealso(self, target: str) -> bool:
        section = self.page.get_section(S.SEEALSO)
        if section is None:
            return self._mark(False)
        kept: list[str] = []
        removed = False
        for item in parse_seealso(section.body):
            if item.target == target.strip() and not removed:
                removed = True
                continue
            kept.append(item.raw)
        if not removed:
            return self._mark(False)
        section.set_body("".join(f"{line}\n" for line in kept))
        return self._mark(True)

    # --- 知识来源 ---
    def add_source(self, kind: str | None, text: str, url: str | None = None) -> bool:
        body = text.strip()
        if url and url not in body:
            body = f"{body} {url}".strip()
        line = f"{kind.strip()}: {body}" if kind and kind.strip() else body
        if not line.strip():
            return self._mark(False)
        section = self.page.ensure_section(S.SOURCES)
        if line in section.body:
            return self._mark(False)
        return self.append_section(S.SOURCES, line + "\n")

    # --- 编辑记录（唯一需要手动调用的日志操作） ---
    def list_edit_records(self) -> list[EditRecord]:
        return self.page.edit_records()

    def add_edit_record(
        self,
        message: str,
        *,
        date: str | None = None,
        author: str | None = None,
    ) -> bool:
        section = self.page.ensure_section(S.LOG)
        records = list(parse_log(section.body)[0])
        records.append(
            EditRecord(
                n=len(records) + 1,
                date=(date or self.today).strip(),
                author=(author if author is not None else self.author) or "\u2014",
                message=message.strip(),
            )
        )
        section.set_body(format_log(records))
        return self._mark(True)

    def amend_edit_record(
        self,
        n: int,
        *,
        message: str | None = None,
        date: str | None = None,
        author: str | None = None,
    ) -> bool:
        section = self.page.get_section(S.LOG)
        if section is None:
            return self._mark(False)
        records = list(parse_log(section.body)[0])
        if not 1 <= n <= len(records):
            return self._mark(False)
        target = records[n - 1]
        updated = EditRecord(
            n=target.n,
            date=(date if date is not None else target.date).strip(),
            author=(author if author is not None else target.author).strip(),
            message=(message if message is not None else target.message).strip(),
        )
        if updated == target:
            return self._mark(False)
        records[n - 1] = updated
        section.set_body(format_log(records))
        return self._mark(True)

    def remove_edit_record(self, n: int) -> bool:
        section = self.page.get_section(S.LOG)
        if section is None:
            return self._mark(False)
        records = list(parse_log(section.body)[0])
        if not 1 <= n <= len(records):
            return self._mark(False)
        del records[n - 1]
        section.set_body(format_log(records) if records else "")
        return self._mark(True)


def _clean_tag(tag: str) -> str:
    return tag.strip().lstrip("#").strip()
