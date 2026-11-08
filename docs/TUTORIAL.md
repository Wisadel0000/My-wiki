# 从零开始用 WikiEncoder（10 分钟）

这份教程从空目录开始，每一步都给出**真实输出**（在 `Python 3.12 + uv` 环境里跑过）。
照着敲一遍，你就掌握了 90% 的日常用法。

> 约定：命令里的 `python` 指项目 venv 里的解释器。
> 如果直接敲 `python` 报 `No module named wikiencoder`，就用 `.\.venv\Scripts\python.exe` 代替。

---

## 1. 建一个空库

```powershell
python -m wikiencoder --root mywiki init
```

```
初始化完成：C:\...\mywiki
```

生成的东西：

| 文件/目录 | 作用 |
|---|---|
| `pages/` | 所有条目，一页一个 `.wiki` 文件 |
| `assets/style.css` | 导出网页时用的样式 |
| `wiki.toml` | 配置：页面目录、默认作者 |
| `SYNTAX.md` | 语法规范（随时可查） |
| `AGENTS.md` | 给 AI agent 的操作说明 |

**先改一下 `wiki.toml`**，把作者填上，后面写编辑记录就不用每次传 `--author`：

```toml
[wiki]
pages = "pages"
author = "我"
```

## 2. 建第一个页面

```powershell
python -m wikiencoder --root mywiki new "卷积定理" --type 定理 --tags "数学,信号处理"
```

它会把新建的内容以 diff 形式打给你：

```
--- a/卷积定理.wiki
+++ b/卷积定理.wiki
@@ -0,0 +1,14 @@
+---
+format: 1
+title: 卷积定理
+type: 定理
+tags: 数学, 信号处理
+created: 2026-10-29
+---
+
+@ 序言
+卷积定理
+
+@ 标识信息框
+
+@ 详细内容
```

要点：
- 文件名就是 slug（`pages/卷积定理.wiki`），中文直接可用
- 只给了标题，所以序言默认也是标题，两个板块是空的，等你填
- **重复新建会被拒绝**（不会覆盖已有页面）

## 3. 往页面里填内容

填信息框（`父级`、`领域` 这两行会进知识图谱）：

```powershell
python -m wikiencoder --root mywiki infobox 卷积定理 set 父级 "[[傅里叶变换]]"
```

追加正文（注意是 `--append`，不是覆盖）：

```powershell
python -m wikiencoder --root mywiki set 卷积定理 详细内容 --append --text "## 陈述`n时域卷积等于频域相乘。"
```

结果：

```
 @ 标识信息框
+父级: [[傅里叶变换]]
 
 @ 详细内容
+## 陈述
+时域卷积等于频域相乘。
```

> 想先看效果再落盘：任何写命令加 `--dry-run`，只输出 diff，不动文件。

## 4. 再建一页，然后把两页连起来

```powershell
python -m wikiencoder --root mywiki new "傅里叶变换" --type 概念 --body "把信号拆成复指数之和。"
python -m wikiencoder --root mywiki see 傅里叶变换 add 卷积定理 --note "对偶关系"
```

第二句在"傅里叶变换"的 `@ 参见` 里写了 `- [[卷积定理]] —— 对偶关系`。

**链接不需要单独登记**：`[[卷积定理]]` 写在任何地方（序言、正文、信息框、参见），
反链和知识图谱都会自动算出来。

## 5. 写编辑记录（唯一需要手动的一步）

```powershell
python -m wikiencoder --root mywiki log 卷积定理 add "创建条目"
```

```markdown
@ 编辑记录
| # | 日期 | 作者 | 说明 |
|---|------|------|------|
| 1 | 2026-10-29 | 我 | 创建条目 |
```

**除了这条命令，没有任何操作会自动写编辑记录。** 这是故意的：
日志记"知识为什么变"，逐字节的历史交给 git。

## 6. 看一眼成果

```powershell
python -m wikiencoder --root mywiki show 卷积定理
```

打印整份文件原文。想结构化看：`show 卷积定理 --json`，
想直接看网页：`show 卷积定理 --html`。

## 7. 检查一下

```powershell
python -m wikiencoder --root mywiki validate
python -m wikiencoder --root mywiki index
python -m wikiencoder --root mywiki link
```

```
没有发现问题 ✅
条目 2，边 2，标签 2
  傅里叶变换: 入链 1 / 出链 1
  卷积定理: 入链 1 / 出链 1
红链 0 条，失效锚点 0 条
```

- `validate`：错误码 + 行号，`error` 级必须修
- `index`：条目数、链接边数、每页出入链数量
- `link`：红链（指向不存在的页）和失效锚点

## 8. 改文件名（别手动改名，用这个）

```powershell
python -m wikiencoder --root mywiki rename 卷积定理 卷积原理
```

它一次做三件事：

1. 把文件改名成 `pages/卷积原理.wiki`
2. **全库改写引用**：别的页面里的 `[[卷积定理]]` → `[[卷积原理]]`
3. **旧名进别名**：新文件的 front matter 多一行 `aliases: 卷积定理`，
   所以老链接、老笔记里的引用依然能解析到

## 9. 导出成网页

```powershell
python -m wikiencoder --root mywiki build -o mywiki/out --site-name "我的知识库"
start mywiki\out\index.html
```

```
已导出 2 个页面、2 个标签页 → mywiki\out
```

产物：`index.html`（按类型分组的首页）、`<slug>.html`、`tag-<标签>.html`、
`assets/style.css`、`index.json`（给前端/搜索用）。全部平铺，双击就能看。

## 10. 在 Python 里用

```python
from wikiencoder import WikiStore, ops, render_page
from wikiencoder.index import WikiIndex

store = WikiStore("mywiki", author="我")

# 读
page = store.load("卷积原理")
page.title                      # '卷积定理'（标题没跟着文件名变）
page.aliases                    # ['卷积定理']
page.infobox_dict()             # {'父级': '[[傅里叶变换]]'}
[l.target for l in page.links()]                # ['傅里叶变换']
[(r.n, r.message) for r in page.edit_records()] # [(1, '创建条目')]

# 改（只改内存）
store.modify("卷积原理", lambda p: ops.add_tag(p, "定理"))
store.load("卷积原理").tags      # ['数学', '信号处理', '定理']

# 查关系
index = WikiIndex(store)
index.backlink_pairs("卷积原理")  # [('傅里叶变换', '傅里叶变换')]

# 渲染（resolver 让不存在的页面显示成红链）
html = render_page(
    page,
    resolver=index.resolver,
    backlinks=index.backlink_pairs("卷积原理"),
).full_html
```

**记住这条分界线**：`ops.*` / `Editor.*` 只改内存，`store.save/modify/update` 才写盘。

## 11. 接下来学什么

| 你想干的事 | 看哪里 |
|---|---|
| 语法细节（围栏、转义、锚点） | `mywiki/SYNTAX.md` |
| 每个 API 的参数含义 | `docs/API.md` |
| 让 agent 帮你维护这个库 | `mywiki/AGENTS.md` |
| 网页样式不对 | 改 `mywiki/assets/style.css` 后重新 `build` |

## 常见卡点

| 现象 | 原因 |
|---|---|
| 改了没生效 | 忘了 `store.save`；或又 `load` 了一次（拿到的是新副本） |
| 编辑记录作者是 `—` | `wiki.toml` 的 `author` 没填，也没传 `--author` |
| 红链一堆 | 目标页还没建；`link` 命令能列出来 |
| 中文乱码 | 命令前加 `-X utf8` |
| `No module named wikiencoder` | 用的是系统 Python，换 `.\.venv\Scripts\python.exe` |
