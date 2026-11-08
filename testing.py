from wikiencoder import WikiStore

store = WikiStore("examples")

page = store.load("傅里叶变换")

def describe(page) -> str:
    lines = [f"# {page.title}   slug={page.slug}  type={page.kind or '-'}  tags={page.tags or '-'}"]
    lead = page.preamble.strip()
    if lead:
        lines.append("  序言    " + lead.splitlines()[0][:50])
    for f in page.infobox_fields():
        lines.append(f"  信息框  {f.key} = {f.value}")
    for h in page.headings():
        lines.append(f"  标题    {'  ' * (h.level - 2)}{h.text}  (#{h.anchor})")
    body = page.get_section("详细内容")
    if body is not None:
        lines.append(f"  正文    {len(body.body)} 字符 / {len(body.body.splitlines())} 行")
    for item in page.seealso_items():
        lines.append(f"  参见    {item.target}" + (f" —— {item.note}" if item.note else ""))
    for src in page.source_items():
        lines.append(f"  来源    [{src.kind or '-'}] {src.text[:40]}")
    for r in page.edit_records():
        lines.append(f"  记录    #{r.n} {r.date} {r.author} {r.message}")
    for l in page.links():
        lines.append(f"  链接    {l.raw}  (在 {l.section}, 第{l.line}行)")
    return "\n".join(lines)

print(describe(page))
