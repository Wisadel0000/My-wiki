"""文件仓库：加载、保存、创建、重命名、删除。

硬约定：
- **原子写**：先写同目录临时文件再 ``os.replace``，永不留下半截文件；
- **幂等**：内容没变时 ``changed=False`` 且不写盘；
- **dry-run**：只看 diff、不落盘；
- 重命名会同步改全库引用，并把旧 slug 追加进别名单（双保险）。
"""

from __future__ import annotations

import difflib
import os
import re
import shutil
import tomllib
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import syntax as S
from .editor import Editor
from .errors import E_SLUG_MISMATCH, Diagnostic
from .model import FrontMatter, Section, WikiPage
from .parser import parse, parse_file
from .serializer import serialize

DEFAULT_EXT = ".wiki"
RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_SPACES = re.compile(r"\s+")


def slugify_title(title: str) -> str:
    """中文标题 → 安全的文件名（保留中文，去掉 Windows 非法字符）。"""
    name = _ILLEGAL.sub("", title.strip())
    name = _SPACES.sub("-", name).strip("-. ")
    if not name:
        return "untitled"
    if name.lower() in RESERVED_NAMES:
        return f"_{name}"
    return name


def _unified_diff(old: str, new: str, path: Path) -> str:
    diff = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{path.name}",
        tofile=f"b/{path.name}",
        n=3,
    )
    return "".join(diff)


def _read_config(root: Path) -> dict:
    """读 ``wiki.toml``（可选）。坏文件直接忽略，不让配置阻塞使用。"""
    path = root / "wiki.toml"
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _write_atomic(path: Path, text: str, *, backup: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup and path.exists():
        shutil.copy2(path, path.with_name(path.name + ".bak"))
    temp = path.with_name(f".{path.name}.tmp")
    with temp.open("wb") as handle:
        handle.write(text.encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


@dataclass
class OpResult:
    """一次写操作的结果。"""

    changed: bool
    path: Path | None = None
    diff: str = ""
    page: WikiPage | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "changed": self.changed,
            "path": str(self.path) if self.path else None,
            "diff": self.diff,
            "warnings": self.warnings,
            "errors": self.errors,
        }

    def __bool__(self) -> bool:
        return self.ok and self.changed


class WikiStore:
    """一个 wiki 目录。"""

    def __init__(
        self,
        root: str | Path,
        *,
        pages: str | None = None,
        author: str = "",
        backup: bool = False,
    ) -> None:
        self.root = Path(root)
        self.config = _read_config(self.root)
        section = self.config.get("wiki", {}) if isinstance(self.config.get("wiki"), dict) else {}
        self.pages_dir = self.root / (pages or section.get("pages") or "pages")
        self.author = author or section.get("author", "")
        self.backup = backup

    # --- 基础 ---
    @property
    def exists(self) -> bool:
        return self.pages_dir.is_dir()

    def path_for(self, slug: str) -> Path:
        return self.pages_dir / f"{slug}{DEFAULT_EXT}"

    def slugs(self) -> list[str]:
        if not self.pages_dir.is_dir():
            return []
        suffix = DEFAULT_EXT
        return sorted(
            path.stem for path in self.pages_dir.iterdir() if path.suffix == suffix
        )

    def __contains__(self, slug: object) -> bool:
        return isinstance(slug, str) and self.path_for(slug).is_file()

    def load(self, slug: str) -> WikiPage:
        path = self.path_for(slug)
        if not path.is_file():
            raise FileNotFoundError(f"页面不存在：{slug}（{path}）")
        page = parse_file(path)
        declared = page.front.get("slug")
        if declared and declared != path.stem:
            page.diagnostics.append(
                Diagnostic(
                    E_SLUG_MISMATCH,
                    f"front matter 的 slug「{declared}」与文件名「{path.stem}」不一致",
                    1,
                    "warn",
                )
            )
        page.slug = path.stem
        return page

    def page(self, slug: str) -> WikiPage:
        """``load`` 的别名。"""
        return self.load(slug)

    def iter_pages(self) -> Iterator[WikiPage]:
        for slug in self.slugs():
            yield self.load(slug)

    def text_for(self, slug: str) -> str:
        return self.path_for(slug).read_bytes().decode("utf-8")

    def editor(self, slug: str) -> Editor:
        return Editor(self.load(slug), author=self.author)

    # --- 写 ---
    def save(self, page: WikiPage, *, dry_run: bool = False) -> OpResult:
        path = page.path if page.path is not None else self.path_for(page.slug)
        text = serialize(page)
        old = path.read_bytes().decode("utf-8") if path.is_file() else ""
        if old == text:
            page.path = path
            return OpResult(changed=False, path=path, page=page)
        diff = _unified_diff(old, text, path)
        if dry_run:
            return OpResult(changed=True, path=path, diff=diff, page=page)
        _write_atomic(path, text, backup=self.backup)
        page.path = path
        page.front.raw = None if page.front.dirty else page.front.raw
        return OpResult(changed=True, path=path, diff=diff, page=page)

    def update(
        self,
        slug: str,
        mutate: Callable[[Editor], object],
        *,
        dry_run: bool = False,
    ) -> OpResult:
        """加载 → 交给编辑函数 → 保存。编辑函数返回 False 视为"没有改动"。"""
        page = self.load(slug)
        editor = Editor(page, author=self.author)
        mutate(editor)
        if not editor.changed:
            return OpResult(changed=False, path=self.path_for(slug), page=page)
        return self.save(page, dry_run=dry_run)

    def modify(
        self,
        slug: str,
        mutate: Callable[[WikiPage], object],
        *,
        dry_run: bool = False,
    ) -> OpResult:
        """函数式更新：直接对 page 应用修改函数（如 ``ops.apply`` 组合）。

        与 :meth:`update` 的区别是不依赖 ``Editor.changed`` 标记，
        而是比较序列化前后的文本，因此任何修改方式都能被正确识别。
        """
        path = self.path_for(slug)
        page = self.load(slug)
        before = path.read_bytes().decode("utf-8")
        mutate(page)
        text = serialize(page)
        if before == text:
            return OpResult(changed=False, path=path, page=page)
        diff = _unified_diff(before, text, path)
        if dry_run:
            return OpResult(changed=True, path=path, diff=diff, page=page)
        _write_atomic(path, text, backup=self.backup)
        page.path = path
        return OpResult(changed=True, path=path, diff=diff, page=page)

    def create(
        self,
        title: str,
        *,
        slug: str | None = None,
        kind: str | None = None,
        tags: list[str] | None = None,
        preamble: str | None = None,
        body: str | None = None,
        extra: dict[str, str] | None = None,
        dry_run: bool = False,
    ) -> OpResult:
        """新建一页（标题即文件名）。已存在则返回错误而不覆盖。"""
        slug = slug or slugify_title(title)
        path = self.path_for(slug)
        if path.exists():
            return OpResult(changed=False, path=path, errors=[f"页面已存在：{slug}"])

        fields: dict[str, str] = {"format": "1", "title": title}
        if kind:
            fields["type"] = kind
        if tags:
            fields["tags"] = ", ".join(tags)
        fields["created"] = date.today().isoformat()
        page = WikiPage(slug=slug, front=FrontMatter(fields=fields, dirty=True))
        page.prologue_raw = "\n"  # front matter 与第一个板块之间留一个空行
        page.ensure_section(S.PREAMBLE).set_body(preamble or title + "\n")
        page.ensure_section(S.INFOBOX).set_body("")
        page.ensure_section(S.BODY).set_body(body or "")
        extra_warnings: list[str] = []
        for name, content in (extra or {}).items():
            if S.resolve_section(name) is not None:
                extra_warnings.append(
                    f"自定义板块「{name}」与规范板块同名，落盘后会被解析成规范板块"
                    "（可能产生重复板块）"
                )
            page.insert_section(
                Section(
                    key=S.EXTRA,
                    title=name,
                    body=content,
                    body_raw=content,
                    head_dirty=True,
                )
            )
        page.path = path
        result = self.save(page, dry_run=dry_run)
        result.warnings.extend(extra_warnings)
        return result

    def delete(self, slug: str, *, dry_run: bool = False) -> OpResult:
        """软删除：移到 ``.trash/``，不直接 rm。"""
        path = self.path_for(slug)
        if not path.is_file():
            return OpResult(changed=False, path=path, errors=[f"页面不存在：{slug}"])
        trash = self.root / ".trash" / path.name
        diff = _unified_diff(self.text_for(slug), "", path)
        if dry_run:
            return OpResult(changed=True, path=path, diff=diff)
        trash.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(trash))
        return OpResult(changed=True, path=trash, diff=diff)

    # --- 重命名 ---
    def rename(self, old: str, new: str, *, dry_run: bool = False) -> OpResult:
        """改文件名 + 全库改写 ``[[旧名]]`` + 旧名进别名。"""
        old_path = self.path_for(old)
        new_path = self.path_for(new)
        if not old_path.is_file():
            return OpResult(changed=False, path=old_path, errors=[f"页面不存在：{old}"])
        if new_path.exists():
            return OpResult(changed=False, path=new_path, errors=[f"目标已存在：{new}"])

        page = self.load(old)
        if old not in page.aliases:
            page.front.set_list("aliases", [*page.aliases, old])

        pattern = re.compile(r"(\[\[)(?:\s*)" + re.escape(old) + r"(?=\s*[\]|#])")
        diffs: list[str] = []
        pending: list[tuple[Path, str]] = []

        for slug in self.slugs():
            text = self.text_for(slug)
            updated = pattern.sub(lambda m: m.group(1) + new, text)
            if slug == old:
                updated_page = parse(updated)
                updated_page.front = page.front
                updated_page.slug = new
                updated = serialize(updated_page)
            if updated != text:
                diffs.append(_unified_diff(text, updated, self.path_for(slug)))
                pending.append((self.path_for(slug), updated))

        diff = "".join(diffs)
        if dry_run:
            return OpResult(changed=True, path=new_path, diff=diff)
        for path, text in pending:
            _write_atomic(path, text, backup=self.backup)
        os.replace(old_path, new_path)
        return OpResult(changed=True, path=new_path, diff=diff)

    # --- 事务 ---
    def transaction(self, *, dry_run: bool = False) -> Transaction:
        return Transaction(self, dry_run=dry_run)


class Transaction:
    """把多次保存攒起来，全部成功才落盘。"""

    def __init__(self, store: WikiStore, *, dry_run: bool = False) -> None:
        self.store = store
        self.dry_run = dry_run
        self._pending: list[WikiPage] = []
        self.results: list[OpResult] = []
        self.committed = False

    def __enter__(self) -> Transaction:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            return False
        self.commit()
        return False

    def add(self, page: WikiPage) -> WikiPage:
        self._pending.append(page)
        return page

    def edit(self, slug: str, mutate: Callable[[Editor], object]) -> Editor:
        page = self.store.load(slug)
        editor = Editor(page, author=self.store.author)
        mutate(editor)
        if editor.changed:
            self._pending.append(page)
        return editor

    def commit(self) -> list[OpResult]:
        self.results = [self.store.save(page, dry_run=self.dry_run) for page in self._pending]
        self.committed = True
        self._pending.clear()
        return self.results

    @property
    def changed(self) -> bool:
        return any(result.changed for result in self.results)
