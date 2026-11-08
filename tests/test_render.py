"""渲染测试：分片、锚点、目录、红链、信息框、编辑记录表格、安全转义。"""

from __future__ import annotations

from textwrap import dedent

from wikiencoder import parse
from wikiencoder.render import render_fragment, render_page

PAGE = dedent(
    """\
    ---
    format: 1
    title: 傅里叶变换
    type: 概念
    tags: 变换, 信号处理
    ---

    @ 序言
    一种把函数从时域映射到频域的[[积分变换]]，是[[傅里叶级数]]的推广。

    @ 标识信息框
    领域: 数学 / 分析
    属性: 线性、可逆
    相关概念: [[傅里叶级数]]、[[卷积定理]]
    标签: #变换

    @ 详细内容
    ## 历史
    傅里叶在 1807 年提出。

    ### 早期工作
    细节。

    ## 定义
    对 $f\\in L^1$，定义

    $$F(\\omega)=\\int f(t)e^{-i\\omega t}dt$$

    ::: text
    # 这里不是标题
    <b>这里是字面标签</b>
    :::

    @ 参见
    - [[拉普拉斯变换]] —— 更一般的形式

    @ 知识来源
    书: 《信号与系统》
    网址: https://example.com/fourier

    @ 编辑记录
    | # | 日期 | 作者 | 说明 |
    |---|------|------|------|
    | 1 | 2024-05-01 | 我 | 创建条目 |
    | 2 | 2024-05-12 | 我 | 补充卷积定理 |
    """
)


def render(**kwargs):
    return render_page(parse(PAGE), **kwargs)


def test_parts_are_independent() -> None:
    result = render()
    parts = result.parts
    assert set(parts) == {
        "meta_html",
        "lead_html",
        "infobox_html",
        "toc_html",
        "body_html",
        "seealso_html",
        "sources_html",
        "log_html",
        "backlinks_html",
    }
    assert all(isinstance(value, str) for value in parts.values())


def test_lead_renders_wikilinks() -> None:
    html = render().lead_html
    assert '<a class="wikilink" href="积分变换.html">积分变换</a>' in html
    assert "傅里叶级数" in html


def test_headings_get_chinese_anchors() -> None:
    html = render().body_html
    assert '<h2 id="历史" class="wiki-heading" data-level="2">' in html
    assert '<h3 id="早期工作"' in html


def test_toc_links_match_body_anchors() -> None:
    result = render()
    assert 'href="#历史"' in result.toc_html
    assert 'href="#定义"' in result.toc_html
    assert 'id="历史"' in result.body_html
    assert result.toc_html.count("<ol") >= 2  # 有嵌套


def test_text_region_is_escaped_and_keeps_literal_hash() -> None:
    result = render()
    assert "&lt;b&gt;这里是字面标签&lt;/b&gt;" in result.body_html
    assert "这里不是标题" in result.body_html
    assert 'id="这里不是标题"' not in result.body_html


def test_infobox_order_links_and_tags() -> None:
    html = render().infobox_html
    assert html.index("领域") < html.index("属性") < html.index("相关概念")
    assert '<a class="wikilink" href="卷积定理.html">卷积定理</a>' in html
    assert '<span class="tag">#变换</span>' in html
    assert "数学 / 分析" in html


def test_seealso_and_sources() -> None:
    result = render()
    assert "拉普拉斯变换" in result.seealso_html
    assert "更一般的形式" in result.seealso_html
    assert "《信号与系统》" in result.sources_html
    assert "example.com" in result.sources_html


def test_log_table_and_summary() -> None:
    html = render().log_html
    assert "共 2 次修改" in html
    assert html.count("<tr>") == 3  # 表头 + 2 条
    assert "补充卷积定理" in html


def test_meta_line_uses_last_record_date() -> None:
    html = render().meta_html
    assert "概念" in html
    assert "2024-05-12" in html
    assert "2 次编辑" in html


def test_math_and_footnote_plugins() -> None:
    html = render().body_html
    assert 'class="math inline"' in html
    assert 'class="math block"' in html


def test_broken_links_are_marked() -> None:
    result = render_page(
        parse(PAGE), resolver=lambda target, anchor: (f"{target}.html", target == "卷积定理")
    )
    assert "wikilink broken" in result.infobox_html
    assert "页面未创建" in result.infobox_html


def test_backlinks_render() -> None:
    result = render(backlinks=[("积分变换", "积分变换"), ("傅里叶级数", "傅里叶级数")])
    assert "被以下条目引用" in result.backlinks_html
    assert 'href="积分变换.html"' in result.backlinks_html


def test_full_page_document() -> None:
    result = render(site_name="我的知识库", css_href="assets/style.css")
    html = result.full_html
    assert html.startswith("<!DOCTYPE html>")
    assert "<title>傅里叶变换 · 我的知识库</title>" in html
    assert 'href="assets/style.css"' in html
    assert '<article class="wiki-page" data-slug=""' in html


def test_css_inline_and_mathjax_flags() -> None:
    result = render(css_href=None, css_inline="body{color:red}", mathjax=True)
    assert "<style>body{color:red}</style>" in result.full_html
    assert "mathjax@3" in result.full_html


def test_toc_can_be_disabled() -> None:
    assert render(toc=False).toc_html == ""


def test_tag_href_returning_none_renders_span() -> None:
    """tag_href 返回 None 表示"标签页不存在"，应退化成不可点的 span。"""
    result = render_page(parse(PAGE), tag_href=lambda tag: None)
    assert '<span class="tag">#变换</span>' in result.infobox_html
    assert 'href="tag-' not in result.infobox_html


def test_render_fragment() -> None:
    assert render_fragment("**粗**").startswith("<p><strong>粗</strong>")
    assert render_fragment("<b>x</b>", mode="text") == "<p>&lt;b&gt;x&lt;/b&gt;</p>"


def test_title_is_escaped_in_full_page() -> None:
    page = parse("@ 序言\nx\n")
    page.title = "<script>alert(1)</script>"
    html = render_page(page).full_html
    assert "&lt;script&gt;" in html
    assert "<script>alert(1)</script>" not in html
