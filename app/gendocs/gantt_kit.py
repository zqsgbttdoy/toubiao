"""横道图（甘特）通用引擎（P1 批次 2A）：底纹时间轴，横向 A4。

在 docx_kit 原子操作之上封装「可配置字段标签」的横道图生成，一份基类覆盖：
人员进退场、施工进度计划、TIS 检查节点等「实体 × 时间区间」的横道图，
仅通过类属性切换列名/图例/默认标题，渲染主体共用。

- 左信息列固定 5 列（序号 + name/role/entry/exit 四字段），标签由子类配置；
- 时间列按 bucketize 自适应粒度（日/周/月），可用 payload.time_scale 指定；
- 已确定结束=蓝色横道 BAR_CONFIRMED，开放式（退场/结束待定）=灰色 BAR_OPEN；
- 每满 50 数据行插入分页符行；两行表头 + 跨页重复。

实体字段统一用 name/role/entry_date/exit_date/note（前端按 columns 元数据渲染）。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Literal

from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..core import now
from .base import AttachmentBuilder
from .column_kit import Column
from .docx_kit import (bucketize, fixed_layout, new_document, repeat_header,
                       set_cell_text, shade_cell, to_bytes, vertical_text)

BAR_CONFIRMED = "4F81BD"  # 蓝色：已确定结束日期的在场/作业时段
BAR_OPEN = "BFBFBF"       # 灰色：结束待定（至工期/活动结束）
HEADER_FILL = "D9E2F3"
INFO_WIDTHS_CM = [1.0, 2.0, 2.5, 2.2, 2.2]
TIME_WIDTH_CM = 0.45
NOTE_WIDTH_CM = 3.0
PAGE_BREAK_EVERY = 50


class GanttRow(BaseModel):
    """横道图通用实体：名称 + 归属 + 起止日期 + 备注。"""
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=50)
    role: str = Field(min_length=1, max_length=100)
    entry_date: date
    exit_date: date | None = None  # None = 至工期/活动结束
    note: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def check_dates(self):
        if self.exit_date and self.entry_date > self.exit_date:
            raise ValueError("开始日期不能晚于结束日期")
        return self


class GanttPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: list[GanttRow] = Field(min_length=1, max_length=200)
    title: str = Field(default="", max_length=200)
    time_scale: Literal["auto", "day", "week", "month"] = "auto"


def _project_deadline(project: dict) -> date | None:
    raw = project.get("deadline")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw)).date()
    except ValueError:
        return None


def _row_height_cm(row, height_cm: float):
    tr_pr = row._tr.get_or_add_trPr()
    tr_height = OxmlElement("w:trHeight")
    tr_height.set(qn("w:val"), str(int(Cm(height_cm).twips)))
    tr_height.set(qn("w:hRule"), "exact")
    tr_pr.append(tr_height)


def _build_buckets(rows, project: dict, time_scale: str):
    start = min(r.entry_date for r in rows)
    ends = [r.exit_date for r in rows if r.exit_date]
    deadline = _project_deadline(project)
    if deadline:
        ends.append(deadline)
    end = max(ends) if ends else date.today() + timedelta(days=90)
    if end < start:
        end = start
    if time_scale == "auto":
        buckets, _ = bucketize(start, end)
    else:
        from .docx_kit import _day_buckets, _month_buckets, _week_buckets
        builders = {"day": _day_buckets, "week": _week_buckets, "month": _month_buckets}
        buckets = builders[time_scale](start, end)
    return buckets, start, end


class GanttBuilder(AttachmentBuilder):
    """横道图生成器基类：子类通过类属性配置列标签、图例与默认标题。"""
    form_type = "gantt"
    business_types = ["supervision", "tis"]
    payload_model = GanttPayload
    default_title = "横道图"
    group_label = "人员信息"
    name_label = "姓名"
    role_label = "岗位"
    entry_label = "进场日期"
    exit_label = "退场日期"
    exit_open_label = "工期结束"
    note_label = "备注"
    legend = "图例：蓝色横道＝计划在场（已确定退场日期）；灰色横道＝在场至工期结束（退场待定）"
    tail = "本表由软件自动生成，人员与日期须人工核对。打印前请在 Word/WPS 中确认页面设置。"

    def form_fields(self) -> list[dict]:
        return []

    def columns_meta(self) -> list[dict]:
        columns = (
            Column("name", self.name_label, 2.0, "center", "text", required=True, max_length=50),
            Column("role", self.role_label, 2.5, "left", "text", required=True, max_length=100),
            Column("entry_date", self.entry_label, 2.2, "center", "date", required=True),
            Column("exit_date", self.exit_label, 2.2, "center", "date"),
            Column("note", self.note_label, 3.0, "left", "text", max_length=500),
        )
        return [c.meta() for c in columns]

    def build(self, payload, project: dict) -> bytes:
        rows = payload.rows
        buckets, start, end = _build_buckets(rows, project, payload.time_scale)
        title = getattr(payload, "title", "") or self.default_title

        doc = new_document(landscape=True)
        heading = doc.add_paragraph()
        heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
        heading_run = heading.add_run(f"{project.get('name', '未命名项目')}　{title}")
        heading_run.font.size = Pt(16)
        heading_run.font.bold = True
        info = doc.add_paragraph(
            f"委托方：{project.get('client') or '未填写'}；生成时间：{now()}；"
            f"时间范围：{start.isoformat()} 至 {end.isoformat()}")
        info.runs[0].font.size = Pt(9)
        legend = doc.add_paragraph(self.legend)
        legend.runs[0].font.size = Pt(9)

        time_count = len(buckets)
        columns = 6 + time_count
        table = doc.add_table(rows=2, cols=columns)
        table.style = "Table Grid"

        first, second = table.rows[0], table.rows[1]
        merged_info = first.cells[0].merge(first.cells[4])
        set_cell_text(merged_info, self.group_label, bold=True, size_pt=10, align=WD_ALIGN_PARAGRAPH.CENTER)
        shade_cell(merged_info, HEADER_FILL)
        note_head = first.cells[-1].merge(second.cells[-1])
        set_cell_text(note_head, self.note_label, bold=True, size_pt=10, align=WD_ALIGN_PARAGRAPH.CENTER)
        shade_cell(note_head, HEADER_FILL)

        month_groups: list[tuple[int, int, str]] = []
        for index, (_label, bucket_start, _bucket_end) in enumerate(buckets):
            month_key = f"{bucket_start.year}年{bucket_start.month}月"
            if month_groups and month_groups[-1][2] == month_key:
                month_groups[-1] = (month_groups[-1][0], index, month_key)
            else:
                month_groups.append((index, index, month_key))
        for group_start, group_end, month_key in month_groups:
            left, right = 5 + group_start, 5 + group_end
            cell = first.cells[left] if left == right else first.cells[left].merge(first.cells[right])
            set_cell_text(cell, month_key, bold=True, size_pt=9, align=WD_ALIGN_PARAGRAPH.CENTER)
            shade_cell(cell, HEADER_FILL)

        for index, header in enumerate(("序号", self.name_label, self.role_label, self.entry_label, self.exit_label)):
            set_cell_text(second.cells[index], header, bold=True, size_pt=9, align=WD_ALIGN_PARAGRAPH.CENTER)
            shade_cell(second.cells[index], HEADER_FILL)
        for offset, (label, _bucket_start, _bucket_end) in enumerate(buckets):
            cell = second.cells[5 + offset]
            set_cell_text(cell, label, size_pt=7.5, align=WD_ALIGN_PARAGRAPH.CENTER)
            vertical_text(cell)
            shade_cell(cell, HEADER_FILL)
        repeat_header(first)
        repeat_header(second)

        for number, entry in enumerate(rows, 1):
            if number > 1 and (number - 1) % PAGE_BREAK_EVERY == 0:
                break_row = table.add_row()
                for cell in break_row.cells:
                    cell.paragraphs[0].add_run().add_break(WD_BREAK.PAGE)
                _row_height_cm(break_row, 0.4)
            row = table.add_row()
            exit_display = entry.exit_date.isoformat() if entry.exit_date else self.exit_open_label
            values = (str(number), entry.name, entry.role, entry.entry_date.isoformat(), exit_display)
            for index, value in enumerate(values):
                set_cell_text(row.cells[index], value, size_pt=9,
                              align=WD_ALIGN_PARAGRAPH.CENTER if index != 2 else None)
            bar_end = entry.exit_date or end
            for offset, (_label, bucket_start, bucket_end) in enumerate(buckets):
                if entry.entry_date <= bucket_end and bucket_start <= bar_end:
                    shade_cell(row.cells[5 + offset], BAR_CONFIRMED if entry.exit_date else BAR_OPEN)
            set_cell_text(row.cells[-1], entry.note, size_pt=8)

        widths = [*INFO_WIDTHS_CM, *([TIME_WIDTH_CM] * time_count), NOTE_WIDTH_CM]
        fixed_layout(table, widths)

        tail = doc.add_paragraph(self.tail)
        tail.runs[0].font.size = Pt(9)
        return to_bytes(doc)


__all__ = ["GanttBuilder", "GanttRow", "GanttPayload", "BAR_CONFIRMED", "BAR_OPEN"]
