"""round-trip 硬指标：``parse`` → ``serialize`` 必须逐字节相同。

这是整个框架的地基测试：编辑工具永远不应该改动它没碰过的字节，
否则 git diff 会被噪音淹没，agent 的改动也没法审。
"""

from __future__ import annotations

import pytest

from wikiencoder import canonicalize, parse, serialize
from wikiencoder.errors import ParseError

FULL = """---
format: 1
title: 傅里叶变换
type: 概念
aliases: FT, Fourier transform
created: 2024-05-01
---

@ 序言
傅里叶变换是一种把函数从时域映射到频域的[[积分变换]]。它把任意信号拆成不同频率的复指数之和。

@ 标识信息框
领域: 数学 / 分析 / 调和分析
父级: [[积分变换]]
属性: 线性、可逆
标签: #变换 #信号处理
备注: 离散形式见 [[离散傅里叶变换]]

@ 目录

@ 详细内容
## 历史
傅里叶在 1807 年提出。

## 定义
对 $f\\in L^1(\\mathbb{R})$，定义
$$F(\\omega)=\\int f(t)e^{-i\\omega t}dt$$

::: text
这里的 @ 行和 # 都不会被解析：
@ 这不是章节
# 这不是标题
:::

## 性质
- 线性
- 时移

@ 参见
- [[拉普拉斯变换]] —— 更一般的形式
- [[离散傅里叶变换]]

@ 知识来源
书: 《信号与系统》Oppenheim 等
网址: https://example.com/fourier

@ 编辑记录
| # | 日期 | 作者 | 说明 |
|---|------|------|------|
| 1 | 2024-05-01 | 我 | 创建条目 |
| 2 | 2024-05-12 | 我 | 补充卷积定理 |
"""

SAMPLES: dict[str, str] = {
    "full": FULL,
    "crlf": FULL.replace("\n", "\r\n"),
    "bom": "\ufeff" + FULL,
    "no_front_matter": "第一段没有板块包裹的正文。\n\n@ 序言\n正文。\n",
    "trailing_blank_lines": "@ 序言\ntext\n\n\n",
    "only_front_matter": "---\ntitle: 空页\n---\n",
    "empty": "",
    "escaped_at": "@ 序言\n\\@ 这行是字面 at。\n",
    "weird_directive_spacing": "@   序言   \n正文。\n",
    "extra_section": "@ 序言\nx\n\n@ 我的附录\n自定义内容\n",
    "custom_mode": "@ 序言 {md}\n**粗体**\n",
    "no_final_newline": "@ 序言\n没有行尾换行",
}


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_roundtrip_is_byte_identical(name: str) -> None:
    text = SAMPLES[name]
    assert serialize(parse(text)) == text


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_canonicalize_is_idempotent(name: str) -> None:
    once = canonicalize(SAMPLES[name])
    assert canonicalize(once) == once


def test_edit_only_touches_target_section() -> None:
    page = parse(FULL)
    body = page.get_section("详细内容")
    assert body is not None
    body.append("## 新增小节\n补充内容。\n")

    out = serialize(page)
    head, _, _ = FULL.partition("@ 详细内容\n")
    assert out.startswith(head + "@ 详细内容\n"), "详细内容之前的字节必须原样保留"

    marker = "@ 参见\n"
    assert out.endswith(FULL[FULL.index(marker) :]), "详细内容之后的板块必须原样保留"
    assert "## 新增小节" in out


def test_new_section_is_inserted_in_canonical_order() -> None:
    page = parse("@ 序言\nx\n\n@ 编辑记录\n")
    page.ensure_section("seealso").append("- [[甲]]\n")
    out = serialize(page)
    assert out.index("@ 序言") < out.index("@ 参见") < out.index("@ 编辑记录")


def test_front_matter_edit_is_applied_without_touching_body() -> None:
    page = parse(FULL)
    page.title = "傅里叶变换（FT）"
    out = serialize(page)
    assert "title: 傅里叶变换（FT）" in out
    assert out.endswith(FULL[FULL.index("@ 序言") :])


def test_fence_inside_body_does_not_split_sections() -> None:
    text = "@ 详细内容\n::: text\n@ 假的章节\n:::\n\n@ 参见\n"
    page = parse(text)
    assert page.section_keys() == ["body", "seealso"]
    assert "@ 假的章节" in page.get_section("body").body
    assert serialize(page) == text


def test_unclosed_fence_reports_line() -> None:
    with pytest.raises(ParseError) as info:
        parse("@ 序言\n::: text\n没有闭合\n")
    assert info.value.code == "E001"
    assert info.value.line == 2


def test_unclosed_front_matter_raises() -> None:
    with pytest.raises(ParseError) as info:
        parse("---\ntitle: x\n")
    assert info.value.code == "E002"
    assert info.value.line == 1
