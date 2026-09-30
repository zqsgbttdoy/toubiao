"""履历版式引擎（P1 批次 2D）：一人一表的表格式简历（边框 + 标签/值 + 主要经历多行）。

监理人员简历表 / 主要人员资历表等「混合（多段 + 表）」附件共用本模块。
每人渲染为一张四列（标签·值·标签·值）边框表单，跨列字段合并，末段「主要经历」按换行
多行呈现；多人之间分页。底层页面（竖向A4）/ 字体（宋体）/ 序列化仍复用 docx_kit。

字段清单由各生成器以 fields 类属性声明（(label, key, span, type) 元组），
引擎据此同时驱动「前端采集列」与「简历表单渲染」，单一数据源、零重复。
"""
from __future__ import annotations

from ..core import now
from .base import AttachmentBuilder
from .column_kit import Column
from .docx_kit import (clean_text, fixed_layout, new_document, set_cell_text,
                       shade_cell, to_bytes)

from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt

LABEL_FILL = "D9E2F3"
COL_WIDTHS_CM = [2.6, 5.8, 2.6, 5.8]
TOTAL_COLS = 4


def _write_multiline(cell, text, size_pt=10, align=None):
    """清空单元格后按换行写入多段文本，统一宋体（与 docx_kit.set_cell_text 同规则）。"""
    cell.text = ""
    lines = str(text).split("\n") if text else [""]
    for index, line in enumerate(lines):
        paragraph = cell.paragraphs[0] if index == 0 else cell.add_paragraph()
        if align is not None:
            paragraph.alignment = align
        run = paragraph.add_run(clean_text(line))
        run.font.name = "宋体"
        run.font.size = Pt(size_pt)
        run._element.get_or_add_rPr()
        rpr = run._element.rPr
        if rpr.rFonts is None:
            rpr.get_or_add_rFonts()
        rpr.rFonts.set(qn("w:eastAsia"), "宋体")


class ResumeBuilder(AttachmentBuilder):
    """表格式简历生成器基类：子类声明 fields（字段清单）即可。"""
    form_type = "resume"
    business_types = ["supervision", "tis"]
    default_title = "人员简历表"
    filename_pattern = "{project_name}_人员简历表.docx"
    person_title = "人员简历表"
    # fields：(label, key, span, col_type, max_length)；span=1 与后一短字段同行，span>1 独占整行。
    fields: tuple = ()
    experience_key: str = "experience"
    experience_label: str = "主要监理经历"
    notice = "本表由软件自动生成，人员资格与经历须人工核对并附证书扫描件后方可用于投标。"

    def form_fields(self) -> list[dict]:
        return []

    def columns_meta(self) -> list[dict]:
        cols = []
        for label, key, span, col_type, max_length in self.fields:
            cols.append(Column(key, label, 3.0, "left", col_type,
                               required=(key == self._primary_key()),
                               max_length=max_length).meta())
        cols.append(Column(self.experience_key, self.experience_label, 6.0, "left",
                           "text", max_length=2000).meta())
        return cols

    def _primary_key(self) -> str:
        return self.fields[0][1]

    def build(self, payload, project: dict) -> bytes:
        doc = new_document(landscape=False)
        people = getattr(payload, "rows", None) or getattr(payload, "people", [])
        heading = doc.add_paragraph()
        heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = heading.add_run(f"{project.get('name', '未命名项目')}　{getattr(payload, 'title', '') or self.default_title}")
        run.font.size = Pt(16)
        run.font.bold = True
        info = doc.add_paragraph(
            f"委托方：{project.get('client') or '未填写'}；生成时间：{now()}；共 {len(people)} 人")
        info.runs[0].font.size = Pt(9)

        for index, person in enumerate(people, 1):
            if index > 1:
                doc.add_page_break()
            self._render_person(doc, person, index)

        tail = doc.add_paragraph(self.notice)
        tail.runs[0].font.size = Pt(9)
        return to_bytes(doc)

    def _value(self, person, key, col_type) -> str:
        raw = getattr(person, key, "")
        if raw is None:
            return ""
        if col_type == "number" and isinstance(raw, float) and raw.is_integer():
            return str(int(raw))
        return clean_text(raw)

    def _render_person(self, doc, person, index: int):
        caption = doc.add_paragraph()
        cap_run = caption.add_run(f"{index}. {getattr(person, self._primary_key(), '') or '人员'}")
        cap_run.font.size = Pt(12)
        cap_run.font.bold = True

        table = doc.add_table(rows=0, cols=TOTAL_COLS)
        table.style = "Table Grid"
        entries = [(label, key, span, col_type) for label, key, span, col_type, _ml in self.fields]

        cursor = 0
        while cursor < len(entries):
            label, key, span, col_type = entries[cursor]
            row = table.add_row()
            if span > 1 or cursor + 1 >= len(entries) or entries[cursor + 1][2] > 1:
                set_cell_text(row.cells[0], label, bold=True, size_pt=10,
                              align=WD_ALIGN_PARAGRAPH.CENTER)
                shade_cell(row.cells[0], LABEL_FILL)
                value = row.cells[1].merge(row.cells[TOTAL_COLS - 1])
                set_cell_text(value, self._value(person, key, col_type), size_pt=10)
                cursor += 1
            else:
                label2, key2, _span2, col_type2 = entries[cursor + 1]
                set_cell_text(row.cells[0], label, bold=True, size_pt=10, align=WD_ALIGN_PARAGRAPH.CENTER)
                set_cell_text(row.cells[1], self._value(person, key, col_type), size_pt=10)
                set_cell_text(row.cells[2], label2, bold=True, size_pt=10, align=WD_ALIGN_PARAGRAPH.CENTER)
                set_cell_text(row.cells[3], self._value(person, key2, col_type2), size_pt=10)
                for li in (0, 2):
                    shade_cell(row.cells[li], LABEL_FILL)
                cursor += 2

        exp_row = table.add_row()
        set_cell_text(exp_row.cells[0], self.experience_label, bold=True, size_pt=10,
                      align=WD_ALIGN_PARAGRAPH.CENTER)
        shade_cell(exp_row.cells[0], LABEL_FILL)
        exp_value = exp_row.cells[1].merge(exp_row.cells[TOTAL_COLS - 1])
        _write_multiline(exp_value, getattr(person, self.experience_key, "") or "", size_pt=10)

        fixed_layout(table, COL_WIDTHS_CM)


__all__ = ["ResumeBuilder"]
