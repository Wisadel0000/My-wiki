"""全库校验：给出带错误码和行号的诊断报告。

``validate_store`` 返回 :class:`Report`；``Report.ok`` 为假表示有 error 级问题。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import syntax as S
from .errors import (
    E_ANCHOR_BROKEN,
    E_LINK_BROKEN,
    E_SELF_LINK,
    E_TITLE_MISSING,
    I_ORPHAN,
    W_DUPLICATE_EXTRA,
    W_DUPLICATE_SECTION,
    W_MISSING_BODY,
    W_MISSING_PREAMBLE,
    W_SECTION_TITLE_COLLISION,
    W_TITLE_DUPLICATE,
    Diagnostic,
    ParseError,
)
from .index import WikiIndex
from .infobox import parse_infobox
from .log import parse_log
from .model import WikiPage


@dataclass
class Report:
    """一次校验的全部诊断。"""

    items: list[Diagnostic] = field(default_factory=list)

    def add(self, diagnostic: Diagnostic) -> None:
        self.items.append(diagnostic)

    def extend(self, diagnostics: list[Diagnostic]) -> None:
        self.items.extend(diagnostics)

    @property
    def errors(self) -> list[Diagnostic]:
        return [item for item in self.items if item.level == "error"]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [item for item in self.items if item.level == "warn"]

    @property
    def infos(self) -> list[Diagnostic]:
        return [item for item in self.items if item.level == "info"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "infos": len(self.infos),
            "items": [
                {"level": item.level, "code": item.code, "line": item.line, "message": item.message}
                for item in self.items
            ],
        }

    def __str__(self) -> str:
        if not self.items:
            return "没有发现问题 ✅"
        lines = [str(item) for item in self.items]
        lines.append(
            f"合计：{len(self.errors)} 个错误 / {len(self.warnings)} 个警告 / "
            f"{len(self.infos)} 条提示"
        )
        return "\n".join(lines)


def lint_page(page: WikiPage, index: WikiIndex, *, slug: str = "") -> Report:
    """单页检查（不依赖跨页信息的部分）。"""
    report = Report()
    slug = slug or page.slug

    if not page.front.get("title"):
        report.add(
            Diagnostic(E_TITLE_MISSING, "缺少 title（建议写在 front matter 里）", 1, "error")
        )

    if "preamble" not in page.section_keys() and not page.prologue_raw.strip():
        report.add(
            Diagnostic(W_MISSING_PREAMBLE, "没有「@ 序言」板块，条目缺少核心定义", 0, "warn")
        )

    infobox = page.get_section(S.INFOBOX)
    if infobox is not None:
        _, infobox_diagnostics = parse_infobox(infobox.body, base_line=infobox.line + 1)
        report.extend(infobox_diagnostics)

    log = page.get_section(S.LOG)
    if log is not None:
        _, log_diagnostics = parse_log(log.body, base_line=log.line + 1)
        report.extend(log_diagnostics)

    seen: dict[str, int] = {}
    extra_titles: dict[str, int] = {}
    for section in page.sections:
        if section.key == S.EXTRA:
            title = section.title.strip()
            if S.resolve_section(title) is not None:
                report.add(
                    Diagnostic(
                        W_SECTION_TITLE_COLLISION,
                        f"自定义板块「{title}」与规范板块同名，会被当成规范板块解析",
                        section.line,
                        "warn",
                    )
                )
            extra_titles[title] = extra_titles.get(title, 0) + 1
            if extra_titles[title] > 1:
                report.add(
                    Diagnostic(
                        W_DUPLICATE_EXTRA,
                        f"自定义板块「{title}」重名（get_section 只返回第一个）",
                        section.line,
                        "warn",
                    )
                )
            continue
        seen[section.key] = seen.get(section.key, 0) + 1
        if seen[section.key] > 1:
            report.add(
                Diagnostic(
                    W_DUPLICATE_SECTION,
                    f"板块「{S.CANONICAL_TITLES.get(section.key, section.key)}」重复",
                    section.line,
                    "warn",
                )
            )

    for link in page.links():
        target = index.resolve(link.target)
        if target is None:
            report.add(
                Diagnostic(
                    E_LINK_BROKEN,
                    f"红链：[[{link.target}]] 指向的页面不存在",
                    link.line,
                    "warn",
                )
            )
            continue
        if target == slug:
            report.add(Diagnostic(E_SELF_LINK, f"自链接：[[{link.target}]]", link.line, "info"))
        if link.anchor and link.anchor not in index.pages[target].anchors:
            report.add(
                Diagnostic(
                    E_ANCHOR_BROKEN,
                    f"锚点不存在：[[{link.target}#{link.anchor}]]",
                    link.line,
                    "warn",
                )
            )
    return report


def validate_store(store, *, index: WikiIndex | None = None) -> Report:
    """整库校验。"""
    index = index or WikiIndex(store)
    report = Report()
    titles: dict[str, str] = {}

    for slug in store.slugs():
        try:
            page = store.load(slug)
        except ParseError as exc:
            report.add(Diagnostic(exc.code, f"{slug}: {exc.message}", exc.line, "error"))
            continue
        # 重复板块由 lint_page 统一检查，这里跳过解析阶段的同名诊断，避免重复报两遍
        report.extend([item for item in page.diagnostics if item.code != W_DUPLICATE_SECTION])
        report.extend(lint_page(page, index, slug=slug).items)

        normalized = page.title.strip().casefold()
        if normalized in titles:
            report.add(
                Diagnostic(
                    W_TITLE_DUPLICATE,
                    f"标题「{page.title}」与「{titles[normalized]}」重复",
                    1,
                    "warn",
                )
            )
        else:
            titles[normalized] = slug

        if not page.get_section(S.BODY):
            report.add(Diagnostic(W_MISSING_BODY, f"{slug}: 没有「详细内容」板块", 0, "info"))

    for slug in index.orphans():
        report.add(Diagnostic(I_ORPHAN, f"孤岛页面：{slug} 没有任何入链或出链", 0, "info"))

    return report
