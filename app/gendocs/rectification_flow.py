"""整改闭环流程表（P2 批次 3B）：复用层级图引擎新增的流程形态。

隐患整改闭环流程图（#38）——监理惯用四步（整改通知单→实施整改→复查→闭合归档），
TIS 惯用六步（含方案审核与施工单位拒不上报时的报告机制）；同一模板按业务线增删环节，
环节以「上一环节编号」串联顺序，闭环回路以图例文字示意（表格模拟法，CSP 禁绘图库）。
渲染主体完全复用 FlowBuilder（hierarchy_kit）。
"""
from __future__ import annotations

from .hierarchy_kit import FlowBuilder


class RectificationFlowBuilder(FlowBuilder):
    key = "rectification-flow"
    title = "整改闭环流程表"
    description = "以流程框图展示隐患整改「通知→整改→复查→闭合」闭环各环节责任岗位（监理四步/TIS六步）"
    business_types = ["supervision", "tis"]
    filename_pattern = "{project_name}_整改闭环流程表.docx"
    default_title = "隐患整改闭环流程图"
    legend = ("图示：按「上一环节编号」串联流程顺序，框首「→」表示推进方向，末环节回到复查/归档形成闭环；"
              "监理惯用四步（整改通知单→实施整改→复查→闭合），"
              "TIS 惯用六步（通知→整改方案审核→整改跟踪→复查→闭环→拒不上报时报建设/保险方）。")


__all__ = ["RectificationFlowBuilder"]
