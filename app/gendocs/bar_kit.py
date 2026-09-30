"""柱状图引擎（P1 批次 2B）：人月在场网格 + 每月人力投入堆叠柱状。

报告 #27「人月计划表 / 人力投入直方图」= 混合(甘特 + 柱状)。因 CSP 禁用外部图表库，
柱状只能在 Word 表格内以「单元格堆叠填色」实现（与甘特横道同源，只是把「时间区间」
降采样到「自然月在场」，再按每月在场人数堆叠成柱）。

本模块提供：
- 月度在场计算（on_site / monthly_counts）与两种渲染积木（人月网格表、堆叠柱状表）；
- BarBuilder 基类：子类用 show_grid / show_histogram 开关组合出「人月计划表」或「直方图」。
底层页面（横向A4）/ 字体（宋体）/ 序列化 / 溢出缩放仍复用 docx_kit + column_kit，不重复造轮子。
"""
from __future__ import annotations

from datetime import date

from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..core import now
from .base import AttachmentBuilder
from .column_kit import Column, scale_to_fit
from .docx_kit import (_month_buckets, fixed_layout, new_document, repeat_header,
                       set_cell_text, shade_cell, to_bytes, vertical_text)

PRESENT_FILL = "4F81BD"   # 在场月份 / 柱体：蓝色，与甘特已确定横道一致
BAR_LABEL_FILL = "BFBFBF"  # 柱顶人数标签底纹
HEADER_FILL = "D9E2F3"
COUNT_FILL = "F2F2F2"
MONTH_WIDTH_CM = 1.1
AXIS_WIDTH_CM = 2.2


class BarRow(BaseModel):
    """人月计划输入实体：名称 + 归属 + 起止日期（退场留空＝持续至期末）。

    count 为计划人数（P2 批次 3C 劳动力类附件的人数加权），仅在子类开启
    show_count 时参与在场统计；否则恒按 1 计，保持既有附件行为不变。
    """
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=50)
    role: str = Field(min_length=1, max_length=100)
    entry_date: date
    exit_date: date | None = None
    count: int | None = Field(default=None, ge=1, le=9999, description="计划人数，留空按 1 计")

    @model_validator(mode="after")
    def check_dates(self):
        if self.exit_date and self.entry_date > self.exit_date:
            raise ValueError("进场日期不能晚于退场日期")
        return self


class BarPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: list[BarRow] = Field(min_length=1, max_length=200)
    title: str = Field(default="", max_length=200)


def _project_deadline(project: dict) -> date | None:
    raw = project.get("deadline")
    if not raw:
        return None
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(raw)).date()
    except ValueError:
        return None


def _horizon(rows, project: dict) -> date:
    ends = [r.exit_date for r in rows if r.exit_date]
    deadline = _project_deadline(project)
    if deadline:
        ends.append(deadline)
    start = min(r.entry_date for r in rows)
    end = max(ends) if ends else date.today()
    return end if end >= start else start


def _on_site(row, m_start: date, m_end: date, horizon: date) -> bool:
    bar_end = row.exit_date or horizon
    return row.entry_date <= m_end and m_start <= bar_end


def _month_matrix(rows, project: dict, weight_fn=None):
    """返回 (buckets, matrix, counts, horizon)：matrix[j]=第 j 月在场行列表；
    counts[j]=第 j 月在场人数（weight_fn 加权，默认每行计 1）。"""
    weight = weight_fn or (lambda _row: 1)
    start = min(r.entry_date for r in rows)
    horizon = _horizon(rows, project)
    buckets = _month_buckets(start, horizon)
    matrix, counts = [], []
    for j, (_label, m_start, m_end) in enumerate(buckets):
        present = [row for row in rows if _on_site(row, m_start, m_end, horizon)]
        matrix.append(present)
        counts.append(sum(weight(row) for row in present))
    return buckets, matrix, counts, horizon


class BarBuilder(AttachmentBuilder):
    """柱状图生成器基类：子类配置标签与 show_grid / show_histogram 组合版式。"""
    form_type = "bar"
    business_types = ["supervision", "tis"]
    payload_model = BarPayload
    default_title = "人月计划表"
    name_label = "姓名"
    role_label = "岗位"
    entry_label = "进场日期"
    exit_label = "退场日期"
    exit_open_label = "工期结束"
    legend = "图例：蓝色格＝该人员当月在场；柱体高度＝该月在场人数（人）。"
    tail = "本表由软件自动生成，人员与在场月份须结合批准的配备计划人工核对。打印前请在 Word/WPS 中确认页面设置。"
    show_grid = True
    show_histogram = False
    show_count = False          # 劳动力类附件（P2 3C）：采集并加权「计划人数」列
    count_label = "计划人数"

    def form_fields(self) -> list[dict]:
        return []

    def columns_meta(self) -> list[dict]:
        columns = [
            Column("name", self.name_label, 2.0, "center", "text", required=True, max_length=50),
            Column("role", self.role_label, 2.5, "left", "text", required=True, max_length=100),
        ]
        if self.show_count:
            columns.append(Column("count", self.count_label, 1.4, "center", "number"))
        columns += [
            Column("entry_date", self.entry_label, 2.2, "center", "date", required=True),
            Column("exit_date", self.exit_label, 2.2, "center", "date"),
        ]
        return [c.meta() for c in columns]

    # ── 信息列积木：show_count 开启时在岗位后插入人数列，月区块列位随之偏移 ──
    def _weight(self, row) -> int:
        return (row.count or 1) if self.show_count else 1

    def _info_headers(self) -> list[str]:
        headers = ["序号", self.name_label, self.role_label]
        if self.show_count:
            headers.append(self.count_label)
        return headers + [self.entry_label, self.exit_label]

    def _info_values(self, row, number: int) -> tuple:
        exit_display = row.exit_date.isoformat() if row.exit_date else self.exit_open_label
        values = [str(number), row.name, row.role]
        if self.show_count:
            values.append(str(row.count or 1))
        return tuple(values + [row.entry_date.isoformat(), exit_display])

    def _info_widths_cm(self) -> list[float]:
        widths = [1.0, 2.0, 2.5]
        if self.show_count:
            widths.append(1.4)
        return widths + [2.2, 2.2]

    def _add_heading(self, doc, payload, project, counts):
        title = getattr(payload, "title", "") or self.default_title
        heading = doc.add_paragraph()
        heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = heading.add_run(f"{project.get('name', '未命名项目')}　{title}")
        run.font.size = Pt(16)
        run.font.bold = True
        if self.show_count:
            people = sum(row.count or 1 for row in payload.rows)
            summary = f"工种 {len(payload.rows)} 类·合计 {people} 人；峰值人力 {max(counts) if counts else 0} 人·月"
        else:
            summary = f"人员 {len(payload.rows)} 人；峰值人力 {max(counts) if counts else 0} 人·月"
        info = doc.add_paragraph(
            f"委托方：{project.get('client') or '未填写'}；生成时间：{now()}；{summary}")
        info.runs[0].font.size = Pt(9)
        legend = doc.add_paragraph(self.legend)
        legend.runs[0].font.size = Pt(9)

    def _render_grid(self, doc, payload, buckets, matrix, counts, horizon):
        """人月在场网格：每行一项，在场月份涂蓝；末行给出每月在场人数（加权）。"""
        month_labels = [label for label, _s, _e in buckets]
        info_headers = self._info_headers()
        n_info = len(info_headers)
        headers = info_headers + month_labels
        table = doc.add_table(rows=1, cols=len(headers))
        table.style = "Table Grid"
        head = table.rows[0]
        for index, text in enumerate(headers):
            set_cell_text(head.cells[index], text, bold=True, size_pt=9,
                          align=WD_ALIGN_PARAGRAPH.CENTER)
            if index < n_info:
                shade_cell(head.cells[index], HEADER_FILL)
            else:
                vertical_text(head.cells[index])
                shade_cell(head.cells[index], HEADER_FILL)
        repeat_header(head)

        role_index = 2
        for number, row in enumerate(payload.rows, 1):
            tr = table.add_row()
            for index, value in enumerate(self._info_values(row, number)):
                set_cell_text(tr.cells[index], value, size_pt=9,
                              align=None if index == role_index else WD_ALIGN_PARAGRAPH.CENTER)
            for j, (_label, m_start, m_end) in enumerate(buckets):
                if row in matrix[j]:
                    shade_cell(tr.cells[n_info + j], PRESENT_FILL)

        total = table.add_row()
        set_cell_text(total.cells[0], "合计", bold=True, size_pt=9, align=WD_ALIGN_PARAGRAPH.CENTER)
        set_cell_text(total.cells[1], "每月在场人数", bold=True, size_pt=9, align=WD_ALIGN_PARAGRAPH.CENTER)
        for index in range(2, n_info):
            set_cell_text(total.cells[index], "", size_pt=9)
            shade_cell(total.cells[index], COUNT_FILL)
        shade_cell(total.cells[0], COUNT_FILL)
        shade_cell(total.cells[1], COUNT_FILL)
        for j in range(len(buckets)):
            set_cell_text(total.cells[n_info + j], str(counts[j]), bold=True, size_pt=9,
                          align=WD_ALIGN_PARAGRAPH.CENTER)
            shade_cell(total.cells[n_info + j], COUNT_FILL)

        widths = [*self._info_widths_cm(), *([MONTH_WIDTH_CM] * len(buckets))]
        fixed_layout(table, scale_to_fit(doc.sections[0], widths))
        return table

    def _render_histogram(self, doc, buckets, counts):
        """每月在场人数堆叠柱状：列＝月份，自底向上按人数填色，柱顶标注人数。"""
        max_count = max(counts) if counts else 0
        levels = max(max_count, 1)
        cols = 1 + len(buckets)
        table = doc.add_table(rows=levels + 2, cols=cols)
        table.style = "Table Grid"

        for i in range(levels):
            level = levels - i  # 顶行代表最高人数档位
            axis = table.rows[i].cells[0]
            set_cell_text(axis, str(level), size_pt=8, align=WD_ALIGN_PARAGRAPH.CENTER)
            shade_cell(axis, COUNT_FILL)
            for j, count in enumerate(counts):
                cell = table.rows[i].cells[1 + j]
                set_cell_text(cell, "", size_pt=8, align=WD_ALIGN_PARAGRAPH.CENTER)
                if level <= count:
                    shade_cell(cell, PRESENT_FILL)
                    if level == count:
                        set_cell_text(cell, str(count), bold=True, size_pt=8,
                                      align=WD_ALIGN_PARAGRAPH.CENTER)

        label_row = table.rows[levels]
        set_cell_text(label_row.cells[0], "在场人数(人)", bold=True, size_pt=8, align=WD_ALIGN_PARAGRAPH.CENTER)
        shade_cell(label_row.cells[0], HEADER_FILL)
        for j, (label, _s, _e) in enumerate(buckets):
            cell = label_row.cells[1 + j]
            set_cell_text(cell, label, bold=True, size_pt=8, align=WD_ALIGN_PARAGRAPH.CENTER)
            shade_cell(cell, HEADER_FILL)
        repeat_header(label_row)

        count_row = table.rows[levels + 1]
        set_cell_text(count_row.cells[0], "当月合计", bold=True, size_pt=8, align=WD_ALIGN_PARAGRAPH.CENTER)
        shade_cell(count_row.cells[0], COUNT_FILL)
        for j, count in enumerate(counts):
            set_cell_text(count_row.cells[1 + j], str(count), bold=True, size_pt=8,
                          align=WD_ALIGN_PARAGRAPH.CENTER)

        widths = [AXIS_WIDTH_CM] + [MONTH_WIDTH_CM] * len(buckets)
        fixed_layout(table, scale_to_fit(doc.sections[0], widths))
        return table

    def build(self, payload, project: dict) -> bytes:
        buckets, matrix, counts, horizon = _month_matrix(payload.rows, project, self._weight)
        doc = new_document(landscape=True)
        self._add_heading(doc, payload, project, counts)
        if self.show_grid:
            self._render_grid(doc, payload, buckets, matrix, counts, horizon)
        if self.show_histogram:
            if self.show_grid:
                doc.add_page_break()
            self._add_heading(doc, payload, project, counts)
            self._render_histogram(doc, buckets, counts)
        tail = doc.add_paragraph(self.tail)
        tail.runs[0].font.size = Pt(9)
        return to_bytes(doc)


__all__ = ["BarBuilder", "BarRow", "BarPayload", "PRESENT_FILL"]
