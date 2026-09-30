"""层级图引擎（P1 批次 2E / P2 批次 3B）：用 Word 表格按「层」模拟组织架构图（CSP 禁外部绘图库）。

机构层级图 / TIS 团队层级图 / 整改闭环流程等「层级/流程」类附件共用本模块。
输入为扁平节点列表（id + parent 建立父子/先后关系），两种形态：
- HierarchyBuilder（层级）：按深度 BFS 分层，每层一行，同层节点均分列宽成框，
  子框顶部「│」示意隶属；
- FlowBuilder（流程，P2 批次 3B）：按 parent 链串成单一顺序，蛇形多行排布，
  框内行首「→」示意环节推进，闭环以图例文字示意。
按层/行循环着色，节点框列宽合计超出 A4 横向可用宽度时由 scale_to_fit 自动缩放。
"""
from __future__ import annotations

from collections import defaultdict

from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt
from pydantic import BaseModel, ConfigDict, Field

from ..core import now
from .base import AttachmentBuilder
from .column_kit import Column, scale_to_fit
from .docx_kit import (clean_text, fixed_layout, new_document, shade_cell, to_bytes)

CENTER = WD_ALIGN_PARAGRAPH.CENTER
DEPTH_FILLS = ("D9E2F3", "E2EFDA", "FCE4D6", "FFF2CC", "DEEAF6", "EAD1DC")
USABLE_LANDSCAPE_CM = 29.7 - 3.0


def _set_run(run, size_pt, bold=False):
    run.font.name = "宋体"
    run.font.size = Pt(size_pt)
    run.font.bold = bold
    run._element.get_or_add_rPr()
    rpr = run._element.rPr
    if rpr.rFonts is None:
        rpr.get_or_add_rFonts()
    rpr.rFonts.set(qn("w:eastAsia"), "宋体")


def _segments(count: int, width: int) -> list[tuple[int, int]]:
    """把 width 列尽量均匀地分给 count 个节点，返回 (起始列, 跨度) 列表。"""
    base, rem = divmod(width, count)
    segs, pos = [], 0
    for i in range(count):
        span = base + (1 if i < rem else 0)
        segs.append((pos, span))
        pos += span
    return segs


def _levels(rows) -> list[list]:
    """按 parent 关系做 BFS 分层；parent 缺失或不在集合内的节点视为根。"""
    ids = {row.id for row in rows}
    children = defaultdict(list)
    roots = []
    for row in rows:
        if row.parent and row.parent in ids:
            children[row.parent].append(row)
        else:
            roots.append(row)
    levels, frontier, guard = [], roots, 0
    while frontier and guard <= len(rows):
        levels.append(frontier)
        nxt = []
        for node in frontier:
            nxt.extend(children.get(node.id, []))
        frontier, guard = nxt, guard + 1
    return levels


class HierNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=20, description="节点编号")
    label: str = Field(min_length=1, max_length=50, description="岗位/部门")
    person: str = Field(default="", max_length=50, description="负责人/人员")
    parent: str = Field(default="", max_length=20, description="上级编号")


class HierarchyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: list[HierNode] = Field(min_length=1, max_length=60)
    title: str = Field(default="", max_length=200)


class HierarchyBuilder(AttachmentBuilder):
    """层级图生成器基类：子类配置标题/表头/图例即可。"""
    form_type = "hierarchy"
    business_types = ["supervision", "tis"]
    payload_model = HierarchyPayload
    default_title = "组织机构层级图"
    filename_pattern = "{project_name}_组织层级图.docx"
    id_header = "节点编号"
    label_header = "岗位/部门"
    person_header = "负责人/人员"
    parent_header = "上级编号"
    legend = "图示：每一行为一个管理层级，自上而下逐级汇报；框顶「│」表示与上级的隶属关系。"
    notice = "本图由软件按节点层级自动生成，岗位设置与隶属关系须人工核对后方可用于投标。"

    def form_fields(self) -> list[dict]:
        return []

    def columns_meta(self) -> list[dict]:
        return [
            Column("id", self.id_header, 1.2, "center", "text", required=True, max_length=20).meta(),
            Column("label", self.label_header, 3.0, "left", "text", required=True, max_length=50).meta(),
            Column("person", self.person_header, 2.0, "center", "text", max_length=50).meta(),
            Column("parent", self.parent_header, 1.5, "center", "text", max_length=20).meta(),
        ]

    # ── 子类钩子：分组方式与摘要文案 ──
    def _groups(self, rows) -> list[list]:
        """默认按 parent 做 BFS 分层，每层一行。"""
        return _levels(rows)

    def _summary(self, rows, groups) -> str:
        return f"{len(rows)} 个节点，{len(groups)} 个层级"

    def _box(self, cell, node, fill, connected: bool):
        cell.text = ""
        first = cell.paragraphs[0]
        first.alignment = CENTER
        if connected:
            _set_run(first.add_run("│"), 8)
            label_para = cell.add_paragraph()
            label_para.alignment = CENTER
        else:
            label_para = first
        _set_run(label_para.add_run(clean_text(node.label)), 10, bold=True)
        if node.person:
            person_para = cell.add_paragraph()
            person_para.alignment = CENTER
            _set_run(person_para.add_run(clean_text(node.person)), 9)
        shade_cell(cell, fill)

    def build(self, payload, project: dict) -> bytes:
        groups = self._groups(payload.rows)
        width = max((len(g) for g in groups), default=1)
        ids = {row.id for row in payload.rows}

        doc = new_document(landscape=True)
        title = getattr(payload, "title", "") or self.default_title
        heading = doc.add_paragraph()
        heading.alignment = CENTER
        _set_run(heading.add_run(f"{project.get('name', '未命名项目')}　{title}"), 16, bold=True)
        info = doc.add_paragraph(
            f"委托方：{project.get('client') or '未填写'}；生成时间：{now()}；"
            + self._summary(payload.rows, groups))
        _set_run(info.runs[0], 9)
        legend = doc.add_paragraph(self.legend)
        _set_run(legend.runs[0], 9)

        table = doc.add_table(rows=0, cols=width)
        table.style = "Table Grid"
        for depth, group in enumerate(groups):
            row = table.add_row()
            segs = _segments(len(group), width)
            fill = DEPTH_FILLS[depth % len(DEPTH_FILLS)]
            for node, (start, span) in zip(group, segs):
                cell = row.cells[start] if span == 1 else row.cells[start].merge(row.cells[start + span - 1])
                self._box(cell, node, fill, connected=bool(node.parent and node.parent in ids))

        fixed_layout(table, scale_to_fit(doc.sections[0], [USABLE_LANDSCAPE_CM / width] * width))
        tail = doc.add_paragraph(self.notice)
        _set_run(tail.runs[0], 9)
        return to_bytes(doc)


class FlowBuilder(HierarchyBuilder):
    """流程形态（P2 批次 3B）：按 parent 链串成单一顺序，蛇形多行排布。

    与层级的差异仅在分组与框内连线示意：行首「→」表示从上环节推进；
    渲染主体/列元数据/溢出缩放完全复用 HierarchyBuilder。
    """
    id_header = "环节编号"
    label_header = "环节名称"
    person_header = "责任人/岗位"
    parent_header = "上一环节编号"
    default_title = "工作流程图"
    steps_per_row = 5
    legend = ("图示：按「上一环节编号」串联流程顺序，框首「→」表示推进方向；"
              "末环节按制度要求回到复查/归档环节形成闭环。")
    notice = "本图由软件按环节先后自动生成，整改闭环各环节责任人与时限须人工核对后方可用于投标。"

    def _groups(self, rows) -> list[list]:
        ordered = [node for level in _levels(rows) for node in level]
        if not ordered:
            return [[]]
        return [ordered[i:i + self.steps_per_row]
                for i in range(0, len(ordered), self.steps_per_row)]

    def _summary(self, rows, groups) -> str:
        return f"{len(rows)} 个环节，每行最多 {self.steps_per_row} 框、共 {len(groups)} 行"

    def _box(self, cell, node, fill, connected: bool):
        """流程框：行首内联「→」示意推进，而非顶部竖向连线。"""
        cell.text = ""
        first = cell.paragraphs[0]
        first.alignment = CENTER
        text = ("→ " if connected else "") + clean_text(node.label)
        _set_run(first.add_run(text), 10, bold=True)
        if node.person:
            person_para = cell.add_paragraph()
            person_para.alignment = CENTER
            _set_run(person_para.add_run(clean_text(node.person)), 9)
        shade_cell(cell, fill)


__all__ = ["HierarchyBuilder", "FlowBuilder", "HierNode", "HierarchyPayload"]
