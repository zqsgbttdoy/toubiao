"""段落类附件轻量渲染引擎：标题 + 问候语 + 正文段落 + 签署栏。

投标函、各类承诺书 / 委托书等「文本段落类」附件共用本模块。
生成器只需提供占位符映射（{{key}}），由 fill() 统一替换、缺失项渲染为填空位，
底层页面 / 字体 / 序列化仍复用 docx_kit，不重复造轮子。
"""
from __future__ import annotations

import re

from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt

from .docx_kit import clean_text, new_document, to_bytes

# 占位符语法：{{ key }}，key 为字母 / 数字 / 下划线。
_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")
BLANK = "　　　　　　"  # 全角空格，未填写的占位符显示为可手写补全的填空位


def fill(text: str, mapping: dict) -> str:
    """把 {{key}} 替换为 mapping[key]；缺失 / 空值的占位符替换为填空位。"""
    def _repl(match: re.Match) -> str:
        value = mapping.get(match.group(1))
        if value is None or str(value).strip() == "":
            return BLANK
        return clean_text(value)
    return _PLACEHOLDER_RE.sub(_repl, text)


def add_title(doc, text: str):
    """文档主标题：居中、加粗、18 磅。"""
    paragraph = doc.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.space_after = Pt(16)
    run = paragraph.add_run(clean_text(text))
    run.font.size = Pt(18)
    run.font.bold = True
    return paragraph


def add_greeting(doc, text: str):
    """问候语 / 致函对象：左对齐、加粗、不缩进（如「致：××招标人」。"""
    paragraph = doc.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(6)
    paragraph.paragraph_format.space_after = Pt(6)
    run = paragraph.add_run(clean_text(text))
    run.font.size = Pt(12)
    run.font.bold = True
    return paragraph


def add_body(doc, text: str, indent: bool = True):
    """正文段落：1.5 倍行距、首行缩进两字符；段内 \\n 渲染为换行。"""
    paragraph = doc.add_paragraph()
    fmt = paragraph.paragraph_format
    fmt.line_spacing = 1.5
    fmt.space_after = Pt(6)
    if indent:
        fmt.first_line_indent = Cm(0.74)
    for index, line in enumerate(str(text).split("\n")):
        if index:
            paragraph.add_run().add_break()
        paragraph.add_run(clean_text(line)).font.size = Pt(12)
    return paragraph


def add_sign_block(doc, lines):
    """签署栏：整体右对齐，逐行渲染（投标人盖章 / 法定代表人签字 / 日期）。"""
    for line in lines:
        if not line:
            continue
        paragraph = doc.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        paragraph.paragraph_format.line_spacing = 1.5
        paragraph.paragraph_format.space_after = Pt(2)
        paragraph.add_run(clean_text(line)).font.size = Pt(12)


def add_notice(doc, text: str):
    """页脚免责提示：小字号，提醒人工核对与线下签章。"""
    paragraph = doc.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(12)
    paragraph.add_run(clean_text(text)).font.size = Pt(9)
    return paragraph


__all__ = ["fill", "new_document", "to_bytes", "add_title", "add_greeting",
           "add_body", "add_sign_block", "add_notice", "BLANK"]
