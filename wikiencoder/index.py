"""全库索引：解析目标、反链、图谱、搜索、index.json。

索引是**派生数据**：磁盘上的 ``.wiki`` 才是唯一真相，删掉 ``index.json``
随时可以重建。解析顺序：slug → 别名 → 标题 → 归一化（空格/下划线/连字符/大小写）。
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .links import WikiLink, extract_links
from .model import WikiPage

_EXT = ".wiki"
_NORMALIZE = re.compile(r"[\s_]+")
_SQUEEZE = re.compile(r"-{2,}")

#: 没有写 ``type`` 的页面在 kind 分组里用这个标签
UNCLASSIFIED = "（未分类）"

#: 信息框里表达"从属关系"的键
PARENT_KEYS = ("父级", "父级知识点", "上级", "父概念")
DOMAIN_KEYS = ("领域", "从属领域", "学科")
RELATED_KEYS = ("相关概念", "相关", "应用", "应用场景")


def normalize_key(text: str) -> str:
    """把标题/别名归一化成可比较的键。"""
    key = text.strip().casefold()
    key = _NORMALIZE.sub("-", key)
    return _SQUEEZE.sub("-", key).strip("-")


@dataclass
class PageEntry:
    """索引里的一个页面。"""

    slug: str
    title: str
    kind: str = ""
    tags: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    parents: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    headings: list[str] = field(default_factory=list)
    anchors: list[str] = field(default_factory=list)
    links_out: list[str] = field(default_factory=list)
    backlinks: list[str] = field(default_factory=list)
    records: int = 0
    updated: str = ""
    excerpt: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _excerpt(page: WikiPage, limit: int = 80) -> str:
    text = " ".join(page.preamble.split())
    return text[:limit]


class WikiIndex:
    """整库的内存索引。"""

    def __init__(self, store) -> None:
        self.store = store
        self.pages: dict[str, PageEntry] = {}
        self.raw: dict[str, WikiPage] = {}
        self.edges: list[tuple[str, str, str]] = []
        self._keys: dict[str, str] = {}
        self._build()

    # --- 构建 ---
    def _build(self) -> None:
        for slug in self.store.slugs():
            page = self.store.load(slug)
            self.raw[slug] = page
            self.pages[slug] = PageEntry(
                slug=slug,
                title=page.title,
                kind=page.kind,
                tags=list(page.tags),
                aliases=list(page.aliases),
                headings=[heading.text for heading in page.headings()],
                anchors=[heading.anchor for heading in page.headings()],
                records=len(page.edit_records()),
                updated=(page.edit_records()[-1].date if page.edit_records() else page.created),
                excerpt=_excerpt(page),
            )
            self._register(slug, slug)
            self._register(page.title, slug)
            for alias in page.aliases:
                self._register(alias, slug)

        for slug, page in self.raw.items():
            entry = self.pages[slug]
            for kind, targets in self._typed_links(page):
                for target in targets:
                    resolved = self.resolve(target)
                    if resolved is None:
                        continue
                    entry.links_out.append(resolved)
                    self.edges.append((slug, resolved, kind))
                    self.pages[resolved].backlinks.append(slug)

    def _register(self, key: str, slug: str) -> None:
        normalized = normalize_key(key)
        if normalized and normalized not in self._keys:
            self._keys[normalized] = slug

    def _typed_links(self, page: WikiPage) -> list[tuple[str, list[str]]]:
        """按语义给链接分类：parent / domain / related / seealso / mention。"""
        grouped: dict[str, list[str]] = {
            "parent": [],
            "domain": [],
            "related": [],
            "seealso": [],
            "mention": [],
        }
        for field_item in page.infobox_fields():
            key = field_item.key
            if any(token in key for token in PARENT_KEYS):
                kind = "parent"
            elif any(token in key for token in DOMAIN_KEYS):
                kind = "domain"
            elif any(token in key for token in RELATED_KEYS):
                kind = "related"
            else:
                kind = "mention"
            for link in extract_links(field_item.value):
                grouped[kind].append(link.target)

        for link in page.links():
            if link.section == "infobox":
                continue
            grouped["seealso" if link.section == "seealso" else "mention"].append(link.target)

        entry = self.pages[page.slug]
        entry.parents = [target for target in grouped["parent"] if target]
        entry.domains = [target for target in grouped["domain"] if target]
        entry.related = [target for target in grouped["related"] if target]
        return [(kind, targets) for kind, targets in grouped.items() if targets]

    # --- 查询 ---
    def resolve(self, target: str) -> str | None:
        """把链接目标解析成 slug；未命中返回 ``None``（红链）。"""
        direct = target.strip()
        if direct in self.pages:
            return direct
        return self._keys.get(normalize_key(direct))

    def __contains__(self, target: object) -> bool:
        return isinstance(target, str) and self.resolve(target) is not None

    def get(self, slug: str) -> PageEntry | None:
        return self.pages.get(slug)

    def resolver(self, target: str, anchor: str | None = None) -> tuple[str, bool]:
        """给渲染器用的 resolver。"""
        slug = self.resolve(target)
        if slug is None:
            return f"{target}.html", True
        href = f"{slug}.html" + (f"#{anchor}" if anchor else "")
        return href, False

    def backlinks(self, slug: str) -> list[str]:
        entry = self.pages.get(slug)
        if entry is None:
            return []
        seen: list[str] = []
        for source in entry.backlinks:
            if source not in seen:
                seen.append(source)
        return seen

    def backlink_pairs(self, slug: str) -> list[tuple[str, str]]:
        return [(source, self.pages[source].title) for source in self.backlinks(slug)]

    def broken_links(self) -> list[tuple[str, WikiLink]]:
        """所有指向不存在页面的链接。"""
        broken: list[tuple[str, WikiLink]] = []
        for slug, page in self.raw.items():
            for link in page.links():
                if self.resolve(link.target) is None:
                    broken.append((slug, link))
        return broken

    def broken_anchors(self) -> list[tuple[str, WikiLink]]:
        """目标页存在但锚点不存在的链接。"""
        broken: list[tuple[str, WikiLink]] = []
        for slug, page in self.raw.items():
            for link in page.links():
                if not link.anchor:
                    continue
                target = self.resolve(link.target)
                if target is None:
                    continue
                if link.anchor not in self.pages[target].anchors:
                    broken.append((slug, link))
        return broken

    def orphans(self) -> list[str]:
        """既没人引用、也没有出链的页面。"""
        return [
            slug
            for slug, entry in self.pages.items()
            if not entry.backlinks and not entry.links_out
        ]

    def by_tag(self, tag: str) -> list[str]:
        wanted = tag.strip().lstrip("#").casefold()
        return [
            slug
            for slug, entry in self.pages.items()
            if any(wanted == item.casefold() for item in entry.tags)
        ]

    def tags(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for slug, entry in self.pages.items():
            for tag in entry.tags:
                result.setdefault(tag, []).append(slug)
        return dict(sorted(result.items()))

    def by_kind(self, kind: str) -> list[str]:
        """取某一 kind（front matter 的 type）下的所有 slug。"""
        wanted = kind.strip()
        return [
            slug
            for slug, entry in self.pages.items()
            if (entry.kind or UNCLASSIFIED) == wanted
        ]

    def kinds(self) -> dict[str, list[str]]:
        """``{kind: [slug, ...]}``，方便查看库里已有哪些类型。

        没有写 ``type`` 的页面归到 :data:`UNCLASSIFIED`。
        """
        result: dict[str, list[str]] = {}
        for slug, entry in self.pages.items():
            result.setdefault(entry.kind or UNCLASSIFIED, []).append(slug)
        return dict(sorted(result.items()))

    def graph(self) -> dict:
        return {
            "nodes": [
                {"slug": entry.slug, "title": entry.title, "kind": entry.kind, "tags": entry.tags}
                for entry in self.pages.values()
            ],
            "edges": [
                {"source": source, "target": target, "kind": kind}
                for source, target, kind in self.edges
            ],
        }

    def search(self, query: str, *, limit: int = 20) -> list[PageEntry]:
        needle = query.strip().casefold()
        if not needle:
            return []
        scored: list[tuple[int, str, PageEntry]] = []
        for entry in self.pages.values():
            score = 0
            if needle in entry.title.casefold():
                score += 6
            if any(needle in alias.casefold() for alias in entry.aliases):
                score += 4
            if any(needle in tag.casefold() for tag in entry.tags):
                score += 3
            if any(needle in heading.casefold() for heading in entry.headings):
                score += 2
            page = self.raw.get(entry.slug)
            if page is not None and needle in page.to_text().casefold():
                score += 1
            if score:
                scored.append((score, entry.title, entry))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [entry for _, _, entry in scored[:limit]]

    # --- 导出 ---
    def to_json(self) -> dict:
        return {
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
            "pages": {slug: entry.to_dict() for slug, entry in self.pages.items()},
            "graph": self.graph(),
            "tags": self.tags(),
        }

    def save(self, path: str | Path | None = None) -> Path:
        target = Path(path) if path is not None else Path(self.store.root) / "index.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.to_json(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return target

    def __len__(self) -> int:
        return len(self.pages)
