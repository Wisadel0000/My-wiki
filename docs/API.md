# WikiEncoder API 文档（白话版）

这份文档只说"怎么用"，不讲实现。语法规则看 [SYNTAX.md](../wikiencoder/assets/SYNTAX.md)。

---

## 0. 先记住这张图

```
.wiki 文件  ──parse() / store.load()──▶  WikiPage 对象（内存里）
                                              │
                            ops.xxx() / Editor.xxx()   ← 只改内存，不碰文件
                                              │
                            store.save() / update() / modify()   ← 这一步才写盘
                                              ▼
                                        磁盘上的 .wiki
```

**三句话**：

1. 库**不会自动保存**。改完必须显式 `save`（或直接走 `update` / `modify`）。
2. 每次 `load` 都是**新解析的一份副本**，改它不影响文件，也不影响下一次 `load`。
3. 只改你动过的板块，其它字节原样保留，所以 git diff 干净。

## 1. 五种最常见的事

```python
from wikiencoder import WikiStore, parse, render_page

# ① 只要 HTML（不建库、不落盘）
page = parse(open("某页.wiki", encoding="utf-8").read())
html = render_page(page).full_html

# ② 打开一个 wiki 目录
store = WikiStore("wiki", author="我")
page = store.load("傅里叶变换")

# ③ 改一个字段（内存）
from wikiencoder import ops
ops.add_tag(page, "信号处理")

# ④ 存回去（带 diff 预览）
print(store.save(page, dry_run=True).diff)
store.save(page)

# ⑤ 一步到位（load → 改 → 存）
store.modify("傅里叶变换", lambda p: ops.add_tag(p, "信号处理"))
```

## 2. 分四层找你要的东西

| 层 | 你在干什么 | 用这些 |
|---|---|---|
| 文本层 | 字符串 ⇄ 对象 | `parse` `parse_file` `serialize` `canonicalize` |
| 对象层 | 改一个页面的内容 | `ops.*`（函数式）或 `Editor.*`（类方法） |
| 仓库层 | 读写文件、建删改名 | `WikiStore` |
| 查询/输出层 | 反链、搜索、校验、渲染、导出 | `WikiIndex` `validate_store` `render_page` `export_site` |

---

## 3. 文本层

### `parse(text, *, path=None) -> WikiPage`
**干什么**：把一段 wiki 文本变成对象。不读文件、不碰磁盘。

```python
page = parse("@ 序言\n一段介绍。\n")
page.title          # 没写 front matter 时等于 slug（此时为空字符串）
page.sections       # [Section(...)]
```

结构错误会抛 `ParseError`（带 `.code` 和 `.line`）；语义问题（未知板块等）收在 `page.diagnostics` 里，**不会丢内容**。

### `parse_file(path) -> WikiPage`
**干什么**：读文件再 `parse`。会记下 `page.path`，后面 `store.save(page)` 就写回这个路径。

### `serialize(page) -> str`
**干什么**：对象 → 文本。**没改过的板块逐字节照抄原文**。

```python
assert serialize(parse(text)) == text      # 无损往返
```

### `canonicalize(text) -> str`
**干什么**：把整份文件重排成规范样子（板块名统一、空行统一）。语义不变，**可以反复执行**。

⚠️ 它不是 markdown 格式化工具，只管结构空白。

---

## 4. 对象层：`WikiPage` 和 `Section`

### `WikiPage` 上有什么

**属性（读）**

| 名字 | 说明 |
|---|---|
| `slug` | 文件名（不含 `.wiki`） |
| `title` | front matter 的 `title`，没有就回落成 slug |
| `kind` | front matter 的 `type`（概念/定理/方法…） |
| `tags` `aliases` | 列表 |
| `created` | 创建日期字符串 |
| `meta` | 整个 front matter 的 dict |
| `preamble` | 序言正文（没有 `@ 序言` 时回落首个 `@` 之前的正文） |
| `path` | 来源文件路径（`parse_file` / `store.load` 才有） |
| `diagnostics` | 解析期的诊断列表 |

**方法（查派生结构，全部现算不缓存）**

| 方法 | 返回 |
|---|---|
| `section_keys()` | `["preamble", "infobox", ...]` |
| `get_section(名字)` | `Section` 或 `None`；名字可以用别名（"正文"→详细内容） |
| `has_section(名字)` | `bool` |
| `extras()` | 自定义板块列表 |
| `infobox_fields()` / `infobox_dict()` | `[InfoboxField]` / `{键: 值}` |
| `edit_records()` | `[EditRecord]` |
| `seealso_items()` | `[SeeAlsoItem]` |
| `source_items()` | `[SourceItem]` |
| `headings()` | `[Heading]`（带 `anchor`，目录和跨页锚点校验都用它） |
| `links()` | `[WikiLink]`（全页所有 `[[...]]`，带行号） |
| `to_text()` | 等价于 `serialize(self)` |

改写内容的**唯一**入口是 `ops` / `Editor`，别直接怼 `page.sections[0].body`。

### `Section` 上有什么

`key`（规范 key）、`title`（文件里写的名字）、`body`（当前正文）、`body_raw`（原文）、
`effective_mode`（`"md"` / `"text"`）、`is_extra`、`is_empty`。

也可以用 `section.set_body("…")` / `section.append("…")`，但那不会做板块级规范化，一般别用。

---

## 5. 改内容：两种风格，行为完全一致

### 5.1 函数式（推荐给 agent）

全部签名为 `fn(page, 参数...) -> bool`，返回"是否真的改了"，天然幂等。

```python
from functools import partial
from wikiencoder import ops

ops.set_title(page, "傅里叶变换")          # 标题
ops.set_kind(page, "概念")                 # 类型
ops.add_alias(page, "FT")                  # 别名

ops.set_tags(page, ["数学", "变换"])
ops.add_tag(page, "信号处理")
ops.remove_tag(page, "数学")

ops.set_preamble(page, "一段定义。")        # 覆盖序言
ops.append_preamble(page, "再补一句。")     # 追加

ops.set_section(page, "详细内容", "## 定义\n…")   # 整段替换
ops.append_section(page, "详细内容", "## 补充\n…")  # 末尾追加
ops.remove_section(page, "知识来源")

ops.set_infobox(page, "父级", "[[积分变换]]")
ops.remove_infobox(page, "应用")

ops.add_seealso(page, "卷积定理", note="对偶关系")
ops.remove_seealso(page, "卷积定理")

ops.add_source(page, "书", "《信号与系统》")
ops.add_source(page, "网址", "维基百科", url="https://example.com")

# 编辑记录：只有这个需要你明确要求才写
ops.add_edit_record(page, "补充标签", date="2024-06-01", author="我")
ops.amend_edit_record(page, 1, message="改一下说明")
ops.remove_edit_record(page, 2)
```

组合多个操作：

```python
changed = ops.apply(
    page,
    partial(ops.add_tag, tag="信号处理"),
    partial(ops.set_infobox, key="应用", value="信号处理"),
)
```

### 5.2 类方法风格

```python
from wikiencoder import Editor

editor = Editor(page, author="我")
editor.add_tag("信号处理")
editor.set_infobox("父级", "[[积分变换]]")
editor.changed          # 有没有改过
```

`Editor` 的方法名和参数与 `ops` 完全一一对应，只是少了 `page` 参数。

### 5.3 一个要紧的规矩

**`add_edit_record` 之外的编辑都不会写编辑记录。** 这是故意的：
日志记的是"知识为什么变"，字节历史交给 git。

---

## 6. 仓库层：`WikiStore`

```python
store = WikiStore("wiki", author="我")   # 目录里要有 pages/ 子目录（或 wiki.toml 指定）
```

构造参数：

| 参数 | 默认 | 说明 |
|---|---|---|
| `root` | — | wiki 根目录 |
| `pages` | `None` | 页面子目录，缺省读 `wiki.toml` 的 `[wiki] pages`，再缺省 `"pages"` |
| `author` | `""` | 写编辑记录时的默认作者；缺省读 `wiki.toml` |
| `backup` | `False` | 写盘前是否留一个 `.bak` |

### 读

| 方法 | 返回 |
|---|---|
| `slugs()` | 所有 slug（排序） |
| `load(slug)` / `page(slug)` | `WikiPage`（每次都是新副本） |
| `iter_pages()` | 逐页 `WikiPage` |
| `text_for(slug)` | 文件的原始文本 |
| `path_for(slug)` | `Path` |
| `slug in store` | 页面是否存在 |
| `store.editor(slug)` | 拿到带默认作者的 `Editor` |

### 写（**只有这 6 个方法会写盘**）

| 方法 | 干什么 |
|---|---|
| `save(page, dry_run=False)` | 把内存对象写回文件；内容没变则 `changed=False` 且不写 |
| `update(slug, fn, dry_run=False)` | `fn(editor)`，内部 load → 改 → save |
| `modify(slug, fn, dry_run=False)` | `fn(page)`，用文本比对判断有没有变，适合配 `ops.apply` |
| `create(title, *, slug, kind, tags, preamble, body, extra, dry_run)` | 新建（已存在则报错，不覆盖） |
| `delete(slug, dry_run=False)` | **软删除**：移到 `.trash/` |
| `rename(old, new, dry_run=False)` | 改文件名 + 全库改写 `[[旧名]]` + 把旧名追加进别名 |

`rename` 是唯一会动多个文件的操作，先 `dry_run=True` 看 diff 是好习惯。

### 事务：多页一起提交

```python
with store.transaction() as tx:
    tx.edit("甲", lambda ed: ed.add_tag("共同"))
    tx.edit("乙", lambda ed: ed.add_tag("共同"))
# 退出 with 时统一落盘；中途抛异常则一个都不写
```

### 返回值 `OpResult`

所有写操作都返回它：

| 字段 | 说明 |
|---|---|
| `changed` | 是否真的产生了变化（幂等判断用这个） |
| `ok` | 没有 `errors` 时为 True |
| `diff` | unified diff 文本 |
| `path` | 涉及的文件 |
| `page` | 修改后的对象 |
| `errors` / `warnings` | 字符串列表 |
| `to_dict()` | 给 CLI / JSON 用 |
| `bool(result)` | 等价于 `ok and changed` |

```python
result = store.update("某页", lambda ed: ed.add_tag("数学"))
if not result.ok:
    print(result.errors)
elif not result.changed:
    print("本来就有这个标签")
```

---

## 7. 查询层：`WikiIndex`

索引是**派生数据**，随时能重建，删掉 `index.json` 也不心疼。

```python
from wikiencoder.index import WikiIndex

index = WikiIndex(store)          # 建索引（会把全库读一遍）
```

| 方法 | 返回 | 用途 |
|---|---|---|
| `resolve("标题/别名/slug")` | `slug` 或 `None` | 手动解析链接目标 |
| `index["标题"]` | `bool` | `in` 语法 |
| `resolver(target, anchor)` | `(href, 是否红链)` | **直接喂给渲染器**，红链才有样式 |
| `backlinks(slug)` | `[slug]` | 谁引用了我 |
| `backlink_pairs(slug)` | `[(slug, 标题)]` | 喂给渲染器的"被引用"区块 |
| `broken_links()` | `[(slug, WikiLink)]` | 红链清单 |
| `broken_anchors()` | `[(slug, WikiLink)]` | 锚点失效清单 |
| `orphans()` | `[slug]` | 孤岛页面 |
| `by_tag(tag)` / `tags()` | `[slug]` / `{标签: [slug]}` | 标签浏览 |
| `by_kind(kind)` / `kinds()` | `[slug]` / `{类型: [slug]}` | 类型浏览（没写 type 的归到"（未分类）"） |
| `graph()` | `{"nodes": [...], "edges": [...]}` | 画关系图 |
| `search(词, limit=20)` | `[PageEntry]` | 标题/别名/标签/标题行/全文打分 |
| `to_json()` / `save(path=None)` | dict / `Path` | 导出 `index.json` |

`PageEntry` 字段：`slug` `title` `kind` `tags` `aliases` `domains` `parents` `related`
`headings` `anchors` `links_out` `backlinks` `records` `updated` `excerpt`。

关系的 `kind` 有五种：`parent`（父级）、`domain`（领域）、`related`（相关概念/应用）、
`seealso`（参见）、`mention`（正文随便提到的）。

---

## 8. 校验：`validate_store`

```python
from wikiencoder.validate import validate_store, lint_page

report = validate_store(store)
print(report)                 # 逐条打印 + 汇总
report.ok                     # 有没有 error
report.errors / warnings / infos
report.to_dict()              # 给 CLI / JSON
```

`lint_page(page, index, slug="")` 只查单页（链接相关检查需要索引，所以还是要传 `index`）。

检查项：缺 title、缺序言、红链、锚点失效、自链接、重复板块、重复标题、
信息框格式、编辑记录表格格式、孤岛页面、解析期警告。

错误码表见 [SYNTAX.md](../wikiencoder/assets/SYNTAX.md#5-错误码)。

---

## 9. 渲染

### `render_page(page, **选项) -> RenderedPage`

```python
from wikiencoder import render_page

result = render_page(
    page,
    resolver=index.resolver,        # 有了它，未创建的页面才显示成红链
    backlinks=index.backlink_pairs("傅里叶变换"),
    site_name="我的知识库",
)
result.full_html                    # 整页文档
result.parts["body_html"]           # 只要正文那一段
```

| 选项 | 默认 | 说明 |
|---|---|---|
| `resolver` | 恒不红链 | `(目标, 锚点) -> (href, 是否红链)`，用 `index.resolver` |
| `backlinks` | `()` | `[(slug, 标题)]` |
| `toc_depth` | `3` | 目录收到几级标题 |
| `toc` | `True` | 要不要目录 |
| `tag_href` | `None` | `标签 -> 链接`，给了标签才可点 |
| `template` | `"page.html"` | 模板名（可从 `assets/` 覆盖） |
| `css_href` | `"assets/style.css"` | 外链 CSS 地址；`None` 则不引 |
| `css_inline` | `None` | 直接内联的 CSS 文本（做单文件用） |
| `mathjax` | `False` | 是否插 MathJax CDN（默认离线可用） |
| `site_name` | `""` | 出现在 `<title>` 里 |
| `generated_at` | 当前时间 | 页脚时间戳，测试时可固定 |

### `RenderedPage` 有九段

`meta_html` `lead_html` `infobox_html` `toc_html` `body_html`
`seealso_html` `sources_html` `log_html` `backlinks_html`，外加 `full_html`。

用 `result.parts["body_html"]` 或 `render_parts(page)` 直接拿字典。
类名（`.wiki-page` `.wikilink.broken` `.tag` `.math.inline` …）是公开契约。

### 其它渲染入口

| 函数 | 用途 |
|---|---|
| `render_parts(page)` | 只要九段字典 |
| `render_body(page)` | 只要正文那段 |
| `render_fragment(text, mode="md")` | 把任意 markdown / 纯文本片段渲染成 HTML |
| `render_inline(text)` | 行内片段（信息框的值） |
| `render_text(text)` | 纯文本模式 |

---

## 10. 导出成网站

```python
from wikiencoder.export import export_site

result = export_site(store, "out", site_name="我的知识库")
result.count            # 页面数
result.index_html       # out/index.html
result.index_json       # out/index.json
```

`out/` 里是：`index.html`（按类型分组的首页）、`<slug>.html`、`tag-<标签>.html`、
`assets/style.css`、`index.json`。全部平铺，双击就能看。

### 只导出单个页面（增量）

改了一页就想更新一页，不必重建整站：

```python
from wikiencoder.export import export_page

export_page(store, "傅里叶变换", "out")                      # 只出这一页
export_page(store, "傅里叶变换", "out", with_related=True)    # 再带上它引用的和被引用的页
```

`with_related=True` 导出的是**一跳**范围：这页 `[[链接]]` 到的页面 + 引用这页的页面（反链）。
这样导出的 HTML 里链接一跳之内不会 404。

标签链接是**自适应的**：输出目录里已经存在 `tag-<标签>.html` 就渲染成可点链接，
不存在就渲染成不可点的 `.tag` span——所以先全站 `build` 再单页覆盖，标签不会退化。

---

## 11. 低层解析器（想把板块单独拎出来时用）

| 函数 | 返回 |
|---|---|
| `parse_infobox(body)` | `([InfoboxField], [Diagnostic])` |
| `format_infobox(键值对列表)` | 信息框正文 |
| `parse_log(body)` | `([EditRecord], [Diagnostic])` |
| `format_log(记录列表)` | 表格文本（编号自动重排） |
| `parse_seealso(body)` / `parse_sources(body)` | `[SeeAlsoItem]` / `[SourceItem]` |
| `extract_links(text, base_line=1)` | `[WikiLink]` |
| `parse_link("[[a\|b]]")` | `WikiLink` 或 `None` |
| `iter_headings(body, mode)` | `[Heading]`（尊重 `::: text` 围栏） |
| `slugify(标题文字)` | 锚点串（中文保留） |
| `slugify_title(标题)` | 文件名安全化（去 Windows 非法字符） |
| `split_list("a, b、c")` | `["a", "b", "c"]` |

`WikiLink` 字段：`target` `anchor` `label` `embed` `line` `section`；属性 `display`、`raw`。
`Heading` 字段：`level` `text` `anchor` `line`。
`Diagnostic` 字段：`code` `level`（error/warn/info）`message` `line`，`str()` 直接可读。

---

## 12. 常见问题

**Q：我改了 `page`，为什么文件没变？**
A：设计如此——必须 `store.save(page)` 或走 `store.modify/update`。库不做自动保存。

**Q：为什么 `store.load()` 之后看不到我刚才的改动？**
A：每次 `load` 都是从磁盘重新解析的**新副本**。你改的是上一个对象。

**Q：只想看改动、不写盘？**
A：`dry_run=True`，返回的 `OpResult.diff` 就是 unified diff。

**Q：会不会把我手写的格式冲掉？**
A：不会。只有被标记为"改过"的板块会重新排版，其余逐字节保留。
新增板块时会给它前面补一个空行。

**Q：链接里写标题还是写 slug？**
A：都行，解析顺序是 slug → 别名 → 标题 → 归一化（空格/下划线/连字符/大小写不敏感）。

**Q：怎么让未创建的页面显示成红链？**
A：渲染时传 `resolver=index.resolver`。

**Q：编辑记录为什么不自动生成？**
A：日志记"知识为什么变"，一条一个人话；自动生成只会变成噪音。

**Q：并发写会坏文件吗？**
A：不会写坏（临时文件 + `os.replace` 原子替换），但**最后写入者胜**，库不提供锁。
多进程同时写同一页要自己协调。

**Q：中文标题能当文件名吗？**
A：能，slug 默认就是标题（只替换 Windows 非法字符）。URL 里会百分号编码，但能正常打开。

**Q：日期格式？**
A：没有强校验，建议 ISO `2024-05-01`；`2024-05-01 14:30` 也能存。

**Q：想加一个自己的板块？**
A：直接 `ops.set_section(page, "冷知识", "内容")`，或者在文件里写 `@ 冷知识`。
未知板块会保留并按 markdown 渲染，只给一条 `E501` 警告。
