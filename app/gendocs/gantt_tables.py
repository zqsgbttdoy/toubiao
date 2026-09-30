"""横道图类附件生成器（P1 批次 2A）：复用 gantt_kit，仅配置字段标签映射。

施工进度计划横道图（#28）与 TIS 检查节点横道图（#29）——把「实体×时间区间」
按报告字段映射改名即可，渲染主体完全复用甘特通用引擎，零重复代码。
"""
from __future__ import annotations

from .gantt_kit import GanttBuilder

_GANTT_LEGEND = "图例：蓝色横道＝计划时段（已确定结束日期）；灰色横道＝持续至期末（结束待定）"
_GANTT_TAIL = "本表由软件自动生成，工序/节点与日期须结合批准的进度计划人工核对。打印前请在 Word/WPS 中确认页面设置。"


class ScheduleGanttBuilder(GanttBuilder):
    key = "schedule-gantt"
    title = "施工进度计划横道图"
    description = "以横道图形式展示各工序/分段的计划起止时段（甘特复用）"
    business_types = ["supervision", "tis"]
    filename_pattern = "{project_name}_施工进度横道图.docx"
    default_title = "施工进度计划横道图"
    group_label = "工序信息"
    name_label = "工序名称"
    role_label = "所属分部"
    entry_label = "计划开始"
    exit_label = "计划结束"
    exit_open_label = "持续至期末"
    legend = _GANTT_LEGEND
    tail = _GANTT_TAIL


class TisInspectionGanttBuilder(GanttBuilder):
    key = "tis-inspection-gantt"
    title = "TIS 检查节点横道图"
    description = "以横道图排定 TIS 各关键必检节点的计划检查时段（仅 TIS 类）"
    business_types = ["tis"]
    filename_pattern = "{project_name}_TIS检查横道图.docx"
    default_title = "TIS 风险检查节点横道图"
    group_label = "检查节点"
    name_label = "检查节点"
    role_label = "检查阶段"
    entry_label = "计划开始"
    exit_label = "计划结束"
    exit_open_label = "持续至期末"
    legend = _GANTT_LEGEND
    tail = _GANTT_TAIL


__all__ = ["ScheduleGanttBuilder", "TisInspectionGanttBuilder"]
