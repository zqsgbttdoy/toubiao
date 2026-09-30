"""通用列式表格引擎（P0 批次 1C/1D 的核心基类）。

在 docx_kit 原子操作之上封装「列定义驱动」的表格生成，一份基类覆盖：
- 竖向 / 横向 A4（landscape）
- 自动序号列（has_sequence）
- 勾选列（Column.type="bool" → ☑/□，复用 checklist_kit）
- 计算列（Column.value_fn：整行对象 → 展示文本，前端不采集，如「小计=数量×单价」）
- 合计行（子类重写 add_footer_rows）
- 表头着色 + 跨页重复 + 每满 50 行分页符

新增列式附件 = 声明一组 Column + 一个 payload 模型（含 rows），零渲染代码。
前端按 list_builders 暴露的 columns 元数据自动渲染表单，无需逐模板改前端。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Callable, Optional

from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

from ..core import now
from .base import AttachmentBuilder
from .checklist_kit import box
from .docx_kit import (clean_text, fixed_layout, new_document, repeat_header,
                       set_cell_text, shade_cell, to_bytes)

HEADER_FILL = "D9E2F3"   # 表头淡蓝，与 equipment_list 一致
TOTAL_FILL = "F2F2F2"    # 合计行浅灰
PAGE_BREAK_EVERY = 50    # 数据行每满 50 行插入分页符行

_ALIGN_MAP = {
    "left": WD_ALIGN_PARAGRAPH.LEFT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "right": WD_ALIGN_PARAGRAPH.RIGHT,
}


def money(value) -> str:
    """千分位 + 两位小数金额展示；无法解析时原样返回。"""
    if value is None or value == "":
        return ""
    try:
        return f"{Decimal(str(value)):,.2f}"
    except (InvalidOperation, ValueError):
        return clean_text(value)


def to_decimal(value) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def diff_days(start, end) -> str:
    """日期差 +1 的天数展示；任一端缺失或倒挂返回空串。"""
    if start and end:
        days = (end - start).days + 1
        return str(days) if days > 0 else ""
    return ""


def scale_to_fit(section, widths_cm: list) -> list:
    """列宽合计超出页面可用宽度时按比例整体缩小，防止固定布局表格被右边距裁切。

    报告「横向多列易打印溢出」风险的通用缓解：窄表原样保留，仅超宽表按可用宽度缩放。
    """
    usable = section.page_width.cm - section.left_margin.cm - section.right_margin.cm
    total = sum(widths_cm)
    if total > usable > 0:
        factor = usable / total
        return [round(w * factor, 3) for w in widths_cm]
    return list(widths_cm)


@dataclass
class Column:
    """列定义：既驱动后端渲染，也生成前端表单元数据。"""
    key: str
    label: str
    width_cm: float = 3.0
    align: str = "left"                 # left / center / right
    type: str = "text"                  # text / number / date / bool / select
    required: bool = False
    max_length: int = 200
    options: Optional[dict] = None      # select 候选：{value: label}
    placeholder: str = ""
    money: bool = False                 # number 列：渲染时千分位 + 两位小数
    value_fn: Optional[Callable] = None  # 计算列：整行 → 展示文本；非空则前端不采集

    def meta(self) -> dict:
        """给前端的字段描述（计算列不下发）。"""
        data = {"key": self.key, "label": self.label, "type": self.type,
                "required": self.required}
        if self.type == "text":
            data["max_length"] = self.max_length
        if self.options:
            data["options"] = self.options
        if self.placeholder:
            data["placeholder"] = self.placeholder
        return data


def _row_height_cm(row, height_cm: float):
    tr_pr = row._tr.get_or_add_trPr()
    tr_height = OxmlElement("w:trHeight")
    tr_height.set(qn("w:val"), str(int(Cm(height_cm).twips)))
    tr_height.set(qn("w:hRule"), "exact")
    tr_pr.append(tr_height)


class ColumnBuilder(AttachmentBuilder):
    """列式表格生成器基类。子类通常只需声明 columns / payload_model 及少量类属性。"""
    form_type = "table"
    business_types = ["supervision", "tis"]
    columns: tuple[Column, ...] = ()
    has_sequence: bool = True
    landscape: bool = False
    default_title: str = "附件表格"
    header_fill: str = HEADER_FILL
    seq_width_cm: float = 1.2
    body_size_pt: float = 10
    header_size_pt: float = 10
    notice: str = "本表由软件自动生成，内容与数据须人工核对后方可用于投标。打印前请在 Word/WPS 中确认页面设置。"

    # ── 元数据：供前端渲染与输入采集（排除计算列 / 序号列）──
    def input_columns(self) -> list[Column]:
        return [c for c in self.columns if c.value_fn is None]

    def form_fields(self) -> list[dict]:  # 兼容 list_builders 的 letter 分支判断
        return []

    def columns_meta(self) -> list[dict]:
        return [c.meta() for c in self.input_columns()]

    # ── 单元格取值 ──
    def _cell_text(self, column: Column, entry) -> str:
        if column.value_fn is not None:
            return clean_text(column.value_fn(entry))
        raw = getattr(entry, column.key, "")
        if column.type == "bool":
            return box(bool(raw))
        if raw is None:
            return ""
        if column.type == "select" and column.options:
            return clean_text(column.options.get(str(raw), str(raw)))
        if column.money and raw != "":
            return money(raw)
        if isinstance(raw, float) and raw.is_integer():
            return str(int(raw))
        return clean_text(raw)

    def _alignment(self, column: Column):
        if column.type == "bool":
            return WD_ALIGN_PARAGRAPH.CENTER
        return _ALIGN_MAP.get(column.align)

    # ── 子类可重写：追加合计 / 统计行 ──
    def add_footer_rows(self, payload, table, col_offset: int):
        return

    def build(self, payload, project: dict) -> bytes:
        doc = new_document(landscape=self.landscape)
        title = getattr(payload, "title", "") or self.default_title
        rows = getattr(payload, "rows", [])

        heading = doc.add_paragraph()
        heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
        heading_run = heading.add_run(f"{project.get('name', '未命名项目')}　{title}")
        heading_run.font.size = Pt(16)
        heading_run.font.bold = True

        info = doc.add_paragraph(
            f"委托方：{project.get('client') or '未填写'}；生成时间：{now()}；共 {len(rows)} 行")
        info.runs[0].font.size = Pt(9)
        if self.landscape:
            hint = doc.add_paragraph("提示：本页为横向版式；若列数较多仍显示不全，请在打印设置中选择「按纸张大小缩放」或调整列宽。")
            hint.runs[0].font.size = Pt(8)

        headers = (["序号"] if self.has_sequence else []) + [c.label for c in self.columns]
        widths = ([self.seq_width_cm] if self.has_sequence else []) + [c.width_cm for c in self.columns]
        total_cols = len(headers)

        table = doc.add_table(rows=1, cols=total_cols)
        table.style = "Table Grid"
        header_row = table.rows[0]
        for index, header in enumerate(headers):
            set_cell_text(header_row.cells[index], header, bold=True,
                          size_pt=self.header_size_pt, align=WD_ALIGN_PARAGRAPH.CENTER)
            shade_cell(header_row.cells[index], self.header_fill)
        repeat_header(header_row)

        for number, entry in enumerate(rows, 1):
            if number > 1 and (number - 1) % PAGE_BREAK_EVERY == 0:
                break_row = table.add_row()
                for cell in break_row.cells:
                    cell.paragraphs[0].add_run().add_break(WD_BREAK.PAGE)
                _row_height_cm(break_row, 0.4)
            row = table.add_row()
            offset = 0
            if self.has_sequence:
                set_cell_text(row.cells[0], str(number), size_pt=self.body_size_pt,
                              align=WD_ALIGN_PARAGRAPH.CENTER)
                offset = 1
            for j, column in enumerate(self.columns):
                set_cell_text(row.cells[offset + j], self._cell_text(column, entry),
                              size_pt=self.body_size_pt, align=self._alignment(column))

        self.add_footer_rows(payload, table, offset)

        fixed_layout(table, scale_to_fit(doc.sections[0], widths))
        tail = doc.add_paragraph(self.notice)
        tail.runs[0].font.size = Pt(9)
        return to_bytes(doc)


__all__ = ["Column", "ColumnBuilder", "money", "to_decimal", "diff_days",
           "scale_to_fit", "HEADER_FILL", "TOTAL_FILL"]
