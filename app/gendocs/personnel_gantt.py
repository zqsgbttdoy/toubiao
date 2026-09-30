"""人员进出场横道图生成器：复用 gantt_kit 通用引擎，仅配置人员相关标签。"""
from __future__ import annotations

from .gantt_kit import GanttBuilder, GanttPayload


class PersonnelGanttBuilder(GanttBuilder):
    key = "personnel-gantt"
    title = "人员进退场计划表（横道图）"
    description = "以甘特图形式展示人员在场时段，蓝色横道表示计划在场期间"
    business_types = ["supervision", "tis"]
    filename_pattern = "{project_name}_人员进退场横道图.docx"
    payload_model = GanttPayload
    default_title = "人员进退场计划表"
    group_label = "人员信息"
    name_label = "姓名"
    role_label = "岗位"
    entry_label = "进场日期"
    exit_label = "退场日期"
    exit_open_label = "工期结束"
    note_label = "备注"
