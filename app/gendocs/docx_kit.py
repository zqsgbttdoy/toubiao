"""python-docx 低阶工具箱：页面、底纹、固定布局、时间分桶等原子操作。

各附件生成器只组合本模块函数，不直接操作 OOXML，便于统一维护。
"""
from __future__ import annotations

import calendar
import io
import re
from datetime import date, timedelta

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

A4_WIDTH_CM = 21.0
A4_HEIGHT_CM = 29.7


def clean_text(text) -> str:
    """清除XML非法控制字符，与 exports.clean_xml 同规则。"""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]", "", str(text))


def new_document(landscape: bool = False, margin_cm: float = 1.5):
    """初始化宋体A4文档；landscape=True 时交换宽高并设横向。"""
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "宋体"
    style.font.size = Pt(10.5)
    style.element.get_or_add_rPr()
    rpr = style.element.rPr
    if rpr.rFonts is None:
        rpr.get_or_add_rFonts()
    rpr.rFonts.set(qn("w:eastAsia"), "宋体")
    section = doc.sections[0]
    width, height = Cm(A4_WIDTH_CM), Cm(A4_HEIGHT_CM)
    if landscape:
        section.orientation = WD_ORIENT.LANDSCAPE
        width, height = height, width
    else:
        section.orientation = WD_ORIENT.PORTRAIT
    section.page_width, section.page_height = width, height
    for attr in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(section, attr, Cm(margin_cm))
    return doc


def shade_cell(cell, hex_fill: str):
    """给单元格加纯色底纹（甘特横道核心）。hex_fill 形如 "4F81BD"，不带#。"""
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tc_pr.append(shd)


def fixed_layout(table, widths_cm):
    """关闭自动调整，设 w:tblLayout=fixed 并按列固定宽度（写 tblGrid，合并单元格下仍稳定）。"""
    table.autofit = False
    tbl_pr = table._tbl.tblPr
    layout = tbl_pr.find(qn("w:tblLayout"))
    if layout is None:
        layout = OxmlElement("w:tblLayout")
        tbl_pr.append(layout)
    layout.set(qn("w:type"), "fixed")
    grid = table._tbl.find(qn("w:tblGrid"))
    if grid is not None:
        for column, width in zip(grid.findall(qn("w:gridCol")), widths_cm):
            column.set(qn("w:w"), str(int(Cm(width).twips)))
    for row in table.rows:
        for cell, width in zip(row.cells, widths_cm):
            cell.width = Cm(width)


def repeat_header(row):
    """设置 w:tblHeader，让表头行跨页重复。"""
    tr_pr = row._tr.get_or_add_trPr()
    header = OxmlElement("w:tblHeader")
    header.set(qn("w:val"), "true")
    tr_pr.append(header)


def set_cell_text(cell, text, bold: bool = False, size_pt: float = 9, align=None):
    """清空单元格后写入单段文本，统一宋体。"""
    cell.text = ""
    paragraph = cell.paragraphs[0]
    if align is not None:
        paragraph.alignment = align
    run = paragraph.add_run(clean_text(text))
    run.font.name = "宋体"
    run.font.size = Pt(size_pt)
    run.font.bold = bold
    run._element.get_or_add_rPr()
    rpr = run._element.rPr
    if rpr.rFonts is None:
        rpr.get_or_add_rFonts()
    rpr.rFonts.set(qn("w:eastAsia"), "宋体")
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER


def vertical_text(cell):
    """窄时间列表头文字竖排（btLr：自下而上），避免0.45cm列宽放不下横排日期。"""
    tc_pr = cell._tc.get_or_add_tcPr()
    direction = OxmlElement("w:textDirection")
    direction.set(qn("w:val"), "btLr")
    tc_pr.append(direction)


def _day_buckets(start: date, end: date):
    buckets = []
    day = start
    while day <= end:
        buckets.append((f"{day.month}/{day.day}", day, day))
        day += timedelta(days=1)
    return buckets


def _week_buckets(start: date, end: date):
    # 首桶对齐到所在周的周一，桶区间裁剪到 [start, end] 内。
    buckets = []
    monday = start - timedelta(days=start.weekday())
    while monday <= end:
        sunday = monday + timedelta(days=6)
        buckets.append((f"{monday.month}/{monday.day}", max(monday, start), min(sunday, end)))
        monday += timedelta(days=7)
    return buckets


def _month_buckets(start: date, end: date):
    buckets = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        last_day = calendar.monthrange(year, month)[1]
        first = max(date(year, month, 1), start)
        last = min(date(year, month, last_day), end)
        buckets.append((f"{year}年{month}月", first, last))
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return buckets


def bucketize(start_date: date, end_date: date, max_columns: int = 40):
    """时间粒度自适应分桶，返回 (buckets, granularity)。

    - 跨度≤62天→day；≤180天→week；否则→month
    - 桶数超过 max_columns 时自动升级粒度（day→week→month）
    - 每项为 (label, bucket_start, bucket_end)
    """
    if end_date < start_date:
        start_date, end_date = end_date, start_date
    span = (end_date - start_date).days + 1
    if span <= 62:
        granularity = "day"
    elif span <= 180:
        granularity = "week"
    else:
        granularity = "month"
    builders = {"day": _day_buckets, "week": _week_buckets, "month": _month_buckets}
    order = ["day", "week", "month"]
    buckets = builders[granularity](start_date, end_date)
    while len(buckets) > max_columns and order.index(granularity) < len(order) - 1:
        granularity = order[order.index(granularity) + 1]
        buckets = builders[granularity](start_date, end_date)
    return buckets, granularity


def to_bytes(doc) -> bytes:
    output = io.BytesIO()
    doc.save(output)
    return output.getvalue()
