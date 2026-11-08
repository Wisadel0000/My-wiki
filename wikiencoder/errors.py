"""错误码与诊断信息。

所有解析/校验问题都带错误码（E###）与行号，方便人和 agent 精确定位。
"""

from __future__ import annotations

from dataclasses import dataclass

# --- 错误码 ---------------------------------------------------------------
E_FENCE_UNCLOSED = "E001"  # 围栏 ::: 没有闭合
E_FRONT_UNCLOSED = "E002"  # front matter --- 没有闭合
E_META_LINE = "E101"  # front matter 行格式错误
E_TITLE_MISSING = "E102"  # 缺少 title
E_SLUG_MISMATCH = "E103"  # front matter slug 与文件名不一致
E_ENCODING = "E104"  # 文件不是合法 UTF-8
E_INFOBOX_LINE = "E201"  # 信息框行没有冒号
E_LOG_TABLE = "E301"  # 编辑记录表格格式错误
E_LINK_BROKEN = "E401"  # 红链：目标页面不存在
E_ANCHOR_BROKEN = "E402"  # 跨页锚点不存在
W_UNKNOWN_SECTION = "E501"  # 未知板块名（保留原文）
W_ESCAPED_AT = "E502"  # 行首未转义 @（疑似想写章节）
I_IMPLICIT_PREAMBLE = "E503"  # 首个 @ 之前的正文被当成序言
W_DUPLICATE_SECTION = "E504"  # 同一板块出现多次
W_MISSING_PREAMBLE = "E505"  # 缺少序言
W_TITLE_DUPLICATE = "E506"  # 两个页面标题相同
W_MISSING_BODY = "E507"  # 缺少详细内容
W_SECTION_TITLE_COLLISION = "E508"  # 自定义板块名撞了规范板块名
W_DUPLICATE_EXTRA = "E509"  # 自定义板块重名
I_ORPHAN = "E601"  # 孤岛页面
E_SELF_LINK = "E602"  # 自链接


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """一条诊断信息。"""

    code: str
    message: str
    line: int = 0
    level: str = "warn"  # error | warn | info

    def __str__(self) -> str:
        loc = f" 第{self.line}行" if self.line else ""
        return f"[{self.level.upper()} {self.code}]{loc} {self.message}"


class WikiError(Exception):
    """本框架所有异常的基类。"""


class ParseError(WikiError):
    """结构层面的错误：文件无法被确定性地解析。"""

    def __init__(self, code: str, message: str, line: int = 0) -> None:
        self.code = code
        self.message = message
        self.line = line
        super().__init__(str(Diagnostic(code, message, line, "error")))
