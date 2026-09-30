"""拟投入主要设备/仪器清单生成器：简单列式表格，竖向A4。"""
from __future__ import annotations

from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from pydantic import BaseModel, ConfigDict, Field

from ..core import now
from .base import AttachmentBuilder
from .docx_kit import (fixed_layout, new_document, repeat_header, set_cell_text,
                       shade_cell, to_bytes)

HEADERS = ("序号", "设备名称", "型号规格", "数量", "用途", "校准有效期")
WIDTHS_CM = [1.2, 4.6, 4.0, 1.8, 4.6, 2.8]
HEADER_FILL = "D9E2F3"
PAGE_BREAK_EVERY = 50  # 数据行超过50行时插入分页符行


class EquipmentEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100, description="设备名称")
    model_spec: str = Field(default="", max_length=100, description="型号规格")
    quantity: int = Field(default=1, ge=1, le=9999, description="数量")
    unit: str = Field(default="台", max_length=20, description="单位")
    purpose: str = Field(default="", max_length=200, description="用途")
    calibration_expiry: str = Field(default="", max_length=50, description="校准有效期")


class EquipmentListPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: list[EquipmentEntry] = Field(min_length=1, max_length=200)
    title: str = Field(default="拟投入主要设备清单", max_length=200)


def _row_height_cm(row, height_cm: float):
    tr_pr = row._tr.get_or_add_trPr()
    tr_height = OxmlElement("w:trHeight")
    tr_height.set(qn("w:val"), str(int(Cm(height_cm).twips)))
    tr_height.set(qn("w:hRule"), "exact")
    tr_pr.append(tr_height)


class EquipmentListBuilder(AttachmentBuilder):
    key = "equipment-list"
    title = "拟投入主要设备/仪器表"
    description = "列式表格展示设备名称、型号、数量、用途及校准有效期"
    business_types = ["supervision", "tis"]
    filename_pattern = "{project_name}_设备清单.docx"
    payload_model = EquipmentListPayload

    def build(self, payload: EquipmentListPayload, project: dict) -> bytes:
        doc = new_document()
        heading = doc.add_paragraph()
        heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
        heading_run = heading.add_run(f"{project.get('name', '未命名项目')}　{payload.title}")
        heading_run.font.size = Pt(16)
        heading_run.font.bold = True
        info = doc.add_paragraph(
            f"委托方：{project.get('client') or '未填写'}；生成时间：{now()}；共 {len(payload.rows)} 项")
        info.runs[0].font.size = Pt(9)

        table = doc.add_table(rows=1, cols=len(HEADERS))
        table.style = "Table Grid"
        for index, header in enumerate(HEADERS):
            set_cell_text(table.rows[0].cells[index], header, bold=True, size_pt=10,
                          align=WD_ALIGN_PARAGRAPH.CENTER)
            shade_cell(table.rows[0].cells[index], HEADER_FILL)
        repeat_header(table.rows[0])

        for number, entry in enumerate(payload.rows, 1):
            if number > 1 and (number - 1) % PAGE_BREAK_EVERY == 0:
                break_row = table.add_row()
                for cell in break_row.cells:
                    cell.paragraphs[0].add_run().add_break(WD_BREAK.PAGE)
                _row_height_cm(break_row, 0.4)
            row = table.add_row()
            values = (str(number), entry.name, entry.model_spec,
                      f"{entry.quantity}{entry.unit}", entry.purpose, entry.calibration_expiry)
            for index, value in enumerate(values):
                set_cell_text(row.cells[index], value, size_pt=10,
                              align=WD_ALIGN_PARAGRAPH.CENTER if index in (0, 3, 5) else None)

        fixed_layout(table, WIDTHS_CM)
        tail = doc.add_paragraph("本表由软件自动生成，设备信息与校准有效期须人工核对。打印前请在 Word/WPS 中确认页面设置。")
        tail.runs[0].font.size = Pt(9)
        return to_bytes(doc)
