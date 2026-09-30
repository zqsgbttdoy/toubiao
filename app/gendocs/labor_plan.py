"""劳动力配置计划表（P2 批次 3C）：复用柱状图引擎 + 人数加权扩展。

劳动力配置计划表（#41）——行＝工种/班组而非自然人，每行携带「计划人数」，
月度在场人数＝Σ该月在场工种的人数；网格（工种×月份在场涂色）与直方图（人月柱）
同页组合输出。渲染主体完全复用 BarBuilder（show_count/show_grid/show_histogram 开关组合）。
"""
from __future__ import annotations

from .bar_kit import BarBuilder


class LaborPlanBuilder(BarBuilder):
    key = "labor-plan"
    title = "劳动力配置计划表"
    description = "按工种列示计划人数与进出场时间，生成工种×月份在场网格及每月在场人数直方图"
    business_types = ["supervision", "tis"]
    filename_pattern = "{project_name}_劳动力配置计划表.docx"
    default_title = "劳动力配置计划表"
    name_label = "工种/班组"
    role_label = "专业/班次"
    count_label = "计划人数"
    entry_label = "进场时间"
    exit_label = "退场时间"
    exit_open_label = "至工期结束"
    legend = "图例：蓝色格＝该工种当月在场；柱体高度＝该月在场计划人数（人）。"
    tail = ("本表由软件按工种与计划人数自动生成，劳动力投入强度须结合施工组织设计与"
            "批准的人员配备计划人工核对。打印前请在 Word/WPS 中确认页面设置。")
    show_grid = True
    show_histogram = True
    show_count = True


__all__ = ["LaborPlanBuilder"]
