# WikiEncoder

纯文本个人 wiki 框架：**一页一个 `.wiki` 文件**，只靠 4 种语法元素
（元数据块 / `@` 板块 / `:::` 围栏 / `[[链接]]`），既能手写、也便于 agent 操作。
Python 库 + CLI，提供无损读写、结构化编辑、HTML 渲染与静态站点导出。

## 安装

```bash
pip install -r requirements.txt      # 运行时依赖
# 或
uv sync --extra dev                  # 开发（含 pytest / ruff / mypy）
```

Python ≥ 3.11。

## 快速开始

```bash
python -m wikiencoder --root wiki init
python -m wikiencoder --root wiki new "傅里叶变换" --type 概念 --tags "数学,变换"
python -m wikiencoder --root wiki infobox 傅里叶变换 set 父级 "[[积分变换]]"
python -m wikiencoder --root wiki see 傅里叶变换 add 积分变换 --note "更一般的形式"
python -m wikiencoder --root wiki log 傅里叶变换 add "创建条目"   # 只有这步会写编辑记录
python -m wikiencoder --root wiki build -o wiki/out
```

`wiki/out/index.html` 双击即可浏览（含首页、每个条目的页面、标签页、`index.json`）。

## 库 API

```python
from wikiencoder import WikiStore, render_page

store = WikiStore("wiki", author="我")
page = store.load("傅里叶变换")

# 结构化编辑（幂等，返回 changed/diff）
store.update("傅里叶变换", lambda ed: ed.add_tag("信号处理"))
store.update("傅里叶变换", lambda ed: ed.add_edit_record("补充标签"))

# 渲染：九段独立 HTML + 整页
rendered = render_page(page, backlinks=[("积分变换", "积分变换")])
rendered.parts["body_html"], rendered.full_html

# 校验 / 索引 / 重命名
from wikiencoder.index import WikiIndex
from wikiencoder.validate import validate_store

index = WikiIndex(store)          # 反链、图谱、搜索
print(index.backlink_pairs("傅里叶变换"))
print(validate_store(store))      # 带错误码与行号
store.rename("傅里叶变换", "FT")   # 改文件名 + 全库改写引用 + 留别名
```

## 保证

| 保证 | 含义 |
|---|---|
| 无损 round-trip | `parse` → `serialize` 逐字节相同（含 CRLF / BOM / 未知板块） |
| 最小改动 | 只重排被编辑的板块，其余字节不动，git diff 干净 |
| 原子写 | 临时文件 + `os.replace`，不会留下半截文件 |
| 幂等 | 内容没变时 `changed=False`，不写盘 |
| dry-run | 所有写操作可只输出 unified diff |
| 派生不落盘 | 目录 / 总修改次数 / 更新时间 / 反链全部现算 |

## 目录结构

```
wikiencoder/
  syntax.py parser.py serializer.py    # 文本 ⇄ 结构（无损）
  model.py editor.py                   # 数据模型与结构化编辑
  infobox.py log.py blocks.py links.py toc.py
  store.py index.py validate.py        # 仓库 / 索引 / 校验
  render/ (markdown.py html.py)        # HTML 渲染
  export.py cli.py                     # 静态导出与命令行
  assets/ (page.html list.html style.css SYNTAX.md AGENTS.md)
tests/      # round-trip / parse / render / store / index / cli
examples/   # 4 个互链示例条目
```

## 文档

| 文档 | 内容 |
|---|---|
| `docs/API.md` | **API 白话版**：分层讲解每个函数、参数、返回值、FAQ |
| `wikiencoder/assets/SYNTAX.md` | 文件语法规范、HTML 契约、19 个错误码（也可 `python -m wikiencoder spec`） |
| `wikiencoder/assets/AGENTS.md` | 给 agent 的操作说明 |

## 设计取舍

- **板块开放式**（`@` 开头、下一个 `@` 结束）：永不会出现标签不匹配，半截编辑也安全。
- **正文默认 markdown**，`::: text` 反向关闭：普通中文段落本来就是合法 markdown，多级标题/锚点/目录免费。
- **链接行内写**（`[[目标]]`）：对称、可扫，且反链与图谱由工具自动维护，不必手写关系表。
- **编辑记录只手动写**：日志记录"知识为什么变"，字节历史交给 git。

## 状态

v1：解析 / 渲染 / 编辑 / 索引 / 校验 / CLI / 静态导出全部完成，测试全绿。
后续可选：本地预览服务器、图片附件管理、MCP 工具封装。
