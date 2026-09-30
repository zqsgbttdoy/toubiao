"""柱状图类附件生成器（P1 批次 2B）：复用 bar_kit，仅配置版式开关。

人月计划表（#27，在场网格 + 每月在场人数合计行）与人力投入直方图（#27，堆叠柱状）
共用 bar_kit 引擎，子类只切换 show_grid / show_histogram 与标签，零渲染代码。
"""
from __future__ import annotations

from .bar_kit import BarBuilder


class ManpowerPlanBuilder(BarBuilder):
    key = "manpower-plan"
    title = "人月计划表"
    description = "以「人员 × 自然月」在场网格展示拟投入人员的人月分布，并汇总每月在场人数"
    business_types = ["supervision", "tis"]
    filename_pattern = "{project_name}_人月计划表.docx"
    default_title = "拟投入人员人月计划表"
    show_grid = True
    show_histogram = False


class ManpowerHistogramBuilder(BarBuilder):
    key = "manpower-histogram"
    title = "人力投入直方图"
    description = "以堆叠柱状图展示各月人力投入（在场人数）的变化趋势"
    business_types = ["supervision", "tis"]
    filename_pattern = "{project_name}_人力投入直方图.docx"
    default_title = "人力投入直方图"
    name_label = "岗位名称"
    role_label = "专业"
    entry_label = "进场月份"
    exit_label = "退场月份"
    show_grid = False
    show_histogram = True


__all__ = ["ManpowerPlanBuilder", "ManpowerHistogramBuilder"]
