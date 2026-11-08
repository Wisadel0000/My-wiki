# 给 agent 的操作说明

这个 wiki 的格式是 **纯文本 + 约定标记**，你可以直接读写 `.wiki` 文件，
也可以用 CLI 走结构化接口。两种方式都安全，但请遵守下面的铁律。

## 三条铁律

1. **不要自动生成编辑记录。** 只有用户明确要求记录时才写
   （`wikiencoder log <slug> add "说明"`）。普通内容修改不写日志。
2. **不要改动没被要求的地方。** 工具会保证未修改的部分逐字节不变；
   如果你手工编辑文件，也不要顺手重排格式。
3. **改完跑一次校验。** `wikiencoder validate`，把 `error` 级问题修掉再交付。

## 优先用 CLI（结构化、幂等、可 dry-run）

```bash
wikiencoder list                          # 列出条目
wikiencoder show <slug>                   # 看原文
wikiencoder show <slug> --json            # 看结构化视图
wikiencoder new "标题" --type 概念 --tags "数学,变换"
wikiencoder set <slug> 详细内容 --append --text "## 新小节\n内容"
wikiencoder infobox <slug> set 父级 "[[积分变换]]"
wikiencoder tag <slug> add 信号处理
wikiencoder see <slug> add 积分变换 --note "更一般的形式"
wikiencoder source <slug> "《信号与系统》" --kind 书
wikiencoder log <slug> add "补充证明"      # 只有用户要求时才执行
wikiencoder rename <旧> <新>               # 自动改全库引用 + 留别名
wikiencoder link                           # 红链 / 失效锚点
wikiencoder validate                       # 整库校验
wikiencoder search 关键词
wikiencoder build -o out                   # 导出静态站点
```

所有写命令都支持 `--dry-run`（只输出 unified diff）和 `--json`（机器可读返回）。
失败退出码为 1，输出里带错误码与行号。

## 直接编辑文件时的语法速查

```
---
format: 1
title: 标题
type: 概念
tags: 数学, 变换
---

@ 序言
一句话定义，可以放 [[链接]]。

@ 标识信息框
领域: 数学 / 分析
父级: [[上位概念]]

@ 详细内容
## 小节
markdown 正文（默认按 markdown 渲染）。

@ 参见
- [[相关条目]] —— 一句话说明

@ 知识来源
书: 《书名》作者
网址: https://example.com

@ 编辑记录
| # | 日期 | 作者 | 说明 |
|---|------|------|------|
| 1 | 2024-05-01 | 我 | 创建条目 |
```

要点：
- 板块**只写开头标记，没有结尾标记**；下一个 `@` 或文件结束就是它的结束。
- 默认渲染模式：序言 / 详细内容 / 自定义板块 = markdown；信息框 / 参见 / 来源 / 编辑记录 = 专用解析。
- 需要纯文本区就用 `::: text` … `:::` 包起来。
- 链接一律 `[[目标]]`，目标可以是 slug、别名或标题。

## 常见任务配方

- **新建一个知识点**：`new` → `infobox set 父级/领域` → `set 详细内容 --append` → `see add` 补 2~3 个相关条目。
- **补内容**：`set <slug> 详细内容 --append --text "..."`，不要重写整段。
- **改标题**：用 `rename`，别手动改文件名（会漏掉引用）。
- **查关系**：`--root . link` 看红链；`index --json` 看反链与图谱。
- **交付前**：`validate` 必须通过（无 error）；有红链要问用户是建页还是改链接。

## 不要做的事

- 不要手写目录、总修改次数、更新时间——它们都是派生的，写了也会被覆盖。
- 不要在元数据里写 `slug`（就是文件名）。
- 不要用 `:` 之外的自造标记（比如 `#标题`、`[链接]`）；语法只有 4 种元素。
