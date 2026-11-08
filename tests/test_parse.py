"""结构解析测试：板块、信息框、编辑记录、标题锚点、链接。"""

from __future__ import annotations

from textwrap import dedent

from wikiencoder import parse
from wikiencoder import syntax as S

PAGE = dedent(
    """\
    ---
    format: 1
    title: 卷积定理
    type: 定理
    aliases: Convolution theorem
    tags: 信号处理, 数学
    ---

    @ 序言
    两个函数的卷积的傅里叶变换等于它们傅里叶变换的乘积。

    @ 标识信息框
    领域: 数学 / 信号处理
    父级: [[傅里叶变换]]
    相关概念: [[傅里叶级数]]
    补充说明: 也适用于拉普拉斯变换
      离散形式见 [[离散傅里叶变换]]

    @ 详细内容
    ## 陈述
    内容。

    ## 证明
    ### 第一步
    细节。

    ## 陈述
    重复的标题。

    @ 参见
    - [[拉普拉斯变换]] —— 对应卷积定理
    - [[傅里叶变换]]

    @ 知识来源
    书: 《信号与系统》
    网址: https://example.com/conv

    @ 编辑记录
    | # | 日期 | 作者 | 说明 |
    |---|------|------|------|
    | 1 | 2024-05-01 | 我 | 创建条目 |
    | 2 | 2024-05-20 | 我 | 补充证明 |
    """
)


def test_section_structure() -> None:
    page = parse(PAGE)
    assert page.section_keys() == ["preamble", "infobox", "body", "seealso", "sources", "log"]
    assert page.title == "卷积定理"
    assert page.kind == "定理"
    assert page.aliases == ["Convolution theorem"]
    assert page.tags == ["信号处理", "数学"]


def test_section_aliases_resolve() -> None:
    page = parse("@ 正文\n内容\n\n@ 参考文献\n- 书\n\n@ 修改记录\n")
    assert page.section_keys() == ["body", "sources", "log"]


def test_infobox_fields_and_continuation() -> None:
    page = parse(PAGE)
    fields = page.infobox_dict()
    assert fields["领域"] == "数学 / 信号处理"
    assert fields["父级"] == "[[傅里叶变换]]"
    values = [f.value for f in page.infobox_fields() if f.key == "补充说明"]
    assert values == ["也适用于拉普拉斯变换\n离散形式见 [[离散傅里叶变换]]"]


def test_edit_records() -> None:
    page = parse(PAGE)
    records = page.edit_records()
    assert len(records) == 2
    assert [r.n for r in records] == [1, 2]
    assert records[0].date == "2024-05-01"
    assert records[0].author == "我"
    assert records[1].message == "补充证明"
    assert records[0].line == 41  # 精确到文件行号


def test_headings_and_anchor_dedup() -> None:
    page = parse(PAGE)
    headings = page.headings()
    assert [h.text for h in headings] == ["陈述", "证明", "第一步", "陈述"]
    assert [h.level for h in headings] == [2, 2, 3, 2]
    assert [h.anchor for h in headings] == ["陈述", "证明", "第一步", "陈述-2"]


def test_text_region_is_not_parsed_as_heading() -> None:
    page = parse("@ 详细内容\n::: text\n# 不是标题\n:::\n\n## 真标题\n")
    assert [h.text for h in page.headings()] == ["真标题"]


def test_links_are_extracted_with_section() -> None:
    page = parse(PAGE)
    links = page.links()
    targets = {link.target for link in links}
    assert {"拉普拉斯变换", "傅里叶变换", "离散傅里叶变换"} <= targets
    assert any(lnk.target == "傅里叶变换" and lnk.section == "infobox" for lnk in links)
    assert any(lnk.target == "离散傅里叶变换" and lnk.section == "infobox" for lnk in links)
    assert any(lnk.target == "拉普拉斯变换" and lnk.section == "seealso" for lnk in links)


def test_seealso_items() -> None:
    page = parse(PAGE)
    items = page.seealso_items()
    assert len(items) == 2
    assert items[0].target == "拉普拉斯变换"
    assert items[0].note == "对应卷积定理"
    assert items[1].target == "傅里叶变换"
    assert items[1].note == ""


def test_source_items() -> None:
    page = parse(PAGE)
    items = page.source_items()
    assert items[0].kind == "书"
    assert items[1].kind == "网址"
    assert items[1].url == "https://example.com/conv"


def test_unknown_section_warns_but_is_kept() -> None:
    page = parse("@ 序言\nx\n\n@ 冷知识\n一些补充\n")
    assert page.section_keys() == ["preamble", "extra"]
    codes = [d.code for d in page.diagnostics]
    assert "E501" in codes
    assert page.get_section("冷知识") is not None


def test_implicit_preamble_is_absorbed() -> None:
    page = parse("开场白。\n\n@ 详细内容\n正文\n")
    assert page.preamble.strip() == "开场白。"
    assert any(d.code == "E503" for d in page.diagnostics)


def test_preamble_fallback_without_section() -> None:
    page = parse("只有开场白，没有任何板块。\n")
    assert page.preamble == "只有开场白，没有任何板块。\n"
    assert page.section_keys() == []


def test_lazy_property_is_not_cached() -> None:
    page = parse(PAGE)
    assert page.get_section(S.LOG).key == "log"
    page.get_section(S.LOG).append("")
    assert page.edit_records()  # 仍然能读到
