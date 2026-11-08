"""函数式编辑工具。

所有函数签名统一为 ``fn(page, ...) -> bool``（是否真的改变了内容），
内部委托 :class:`wikiencoder.editor.Editor`，所以和类方法行为完全一致。

两种组合方式：

1. 直接用 :func:`apply` 串联（``functools.partial`` 很好用）::

       from functools import partial
       from wikiencoder.ops import add_tag, apply, set_infobox

       changed = apply(
           page,
           partial(add_tag, tag="信号处理"),
           partial(set_infobox, key="应用", value="信号处理"),
       )

2. 交给仓库一次落盘（带 dry-run / diff / 原子写）::

       store.modify("傅里叶变换", lambda page: apply(
           page,
           partial(add_tag, tag="信号处理"),
           partial(add_edit_record, message="补充标签"),
       ))
"""

from __future__ import annotations

from collections.abc import Callable

from .editor import Editor
from .model import WikiPage

Step = Callable[..., object]


def _editor(page: WikiPage) -> Editor:
    return Editor(page)


# --- 元数据 ---
def set_title(page: WikiPage, title: str) -> bool:
    return _editor(page).set_title(title)


def set_kind(page: WikiPage, kind: str) -> bool:
    return _editor(page).set_kind(kind)


def add_alias(page: WikiPage, alias: str) -> bool:
    return _editor(page).add_alias(alias)


# --- 标签 ---
def set_tags(page: WikiPage, tags: list[str]) -> bool:
    return _editor(page).set_tags(tags)


def add_tag(page: WikiPage, tag: str) -> bool:
    return _editor(page).add_tag(tag)


def remove_tag(page: WikiPage, tag: str) -> bool:
    return _editor(page).remove_tag(tag)


# --- 序言 ---
def set_preamble(page: WikiPage, text: str) -> bool:
    return _editor(page).set_preamble(text)


def append_preamble(page: WikiPage, text: str) -> bool:
    return _editor(page).append_preamble(text)


# --- 通用板块 ---
def set_section(page: WikiPage, name: str, text: str) -> bool:
    return _editor(page).set_section(name, text)


def append_section(page: WikiPage, name: str, text: str) -> bool:
    return _editor(page).append_section(name, text)


def remove_section(page: WikiPage, name: str) -> bool:
    return _editor(page).remove_section(name)


# --- 信息框 ---
def set_infobox(page: WikiPage, key: str, value: str) -> bool:
    return _editor(page).set_infobox(key, value)


def remove_infobox(page: WikiPage, key: str) -> bool:
    return _editor(page).remove_infobox(key)


# --- 参见 / 来源 ---
def add_seealso(page: WikiPage, target: str, note: str = "") -> bool:
    return _editor(page).add_seealso(target, note=note)


def remove_seealso(page: WikiPage, target: str) -> bool:
    return _editor(page).remove_seealso(target)


def add_source(
    page: WikiPage, kind: str | None, text: str, url: str | None = None
) -> bool:
    return _editor(page).add_source(kind, text, url=url)


# --- 编辑记录（唯一需要显式调用的一类操作） ---
def add_edit_record(
    page: WikiPage,
    message: str,
    *,
    date: str | None = None,
    author: str | None = None,
) -> bool:
    return Editor(page, author=author or "").add_edit_record(
        message, date=date, author=author
    )


def amend_edit_record(
    page: WikiPage,
    n: int,
    *,
    message: str | None = None,
    date: str | None = None,
    author: str | None = None,
) -> bool:
    return _editor(page).amend_edit_record(
        n, message=message, date=date, author=author
    )


def remove_edit_record(page: WikiPage, n: int) -> bool:
    return _editor(page).remove_edit_record(n)


# --- 组合 ---
def apply(page: WikiPage, *steps: Step) -> bool:
    """依次执行多个 ``fn(page, ...)``，返回是否至少有一处改变。

    用 ``functools.partial`` 预绑定参数即可，例如
    ``apply(page, partial(add_tag, tag="数学"))``。
    """
    changed = False
    for step in steps:
        changed = bool(step(page)) or changed
    return changed
