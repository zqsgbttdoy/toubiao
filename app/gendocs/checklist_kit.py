"""勾选类附件轻量渲染引擎：□/☑ 符号 + 勾选项段落。

供「无行贿犯罪/无重大违法记录声明」（文本 + 勾选）与「企业资质清单」
（表格 + 勾选列）共用。符号统一使用宋体（调研报告已验证 Word/WPS 支持），
避免字体缺字导致乱码。
"""
from __future__ import annotations

from docx.shared import Cm, Pt

from .docx_kit import clean_text

BOX_CHECKED = "☑"    # U+2611  ballot box with check
BOX_UNCHECKED = "□"  # U+25A1  white square


def box(checked: bool) -> str:
    """按布尔状态返回勾选符号；供表格单元格与段落共用。"""
    return BOX_CHECKED if checked else BOX_UNCHECKED


def add_check_paragraph(doc, label: str, checked: bool = False, *, size_pt: float = 12, indent: bool = True):
    """渲染一个勾选项段落：☑/□ + 两个空格 + 选项文本。"""
    paragraph = doc.add_paragraph()
    fmt = paragraph.paragraph_format
    fmt.line_spacing = 1.5
    fmt.space_after = Pt(4)
    if indent:
        fmt.first_line_indent = Cm(0.74)
    glyph = paragraph.add_run(box(checked))
    glyph.font.size = Pt(size_pt)
    text = paragraph.add_run("  " + clean_text(label))
    text.font.size = Pt(size_pt)
    return paragraph


__all__ = ["BOX_CHECKED", "BOX_UNCHECKED", "box", "add_check_paragraph"]
