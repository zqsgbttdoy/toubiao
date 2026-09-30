"""层级图类附件生成器（P1 批次 2E）：复用 hierarchy_kit，仅配置标题与表头。

项目监理机构层级图（监理类）与 TIS 风险管理团队层级图（TIS 类）——同一「节点×层级」
引擎，子类只切换标题/表头/文件名，渲染主体完全复用，零重复代码。
"""
from __future__ import annotations

from .hierarchy_kit import HierarchyBuilder


class OrgHierarchyBuilder(HierarchyBuilder):
    key = "org-hierarchy"
    title = "项目监理机构层级图"
    description = "以组织架构层级图展示项目监理机构的岗位设置与逐级汇报关系"
    business_types = ["supervision"]
    filename_pattern = "{project_name}_监理机构层级图.docx"
    default_title = "项目监理机构组织层级图"
    label_header = "岗位/部门"


class TisTeamHierarchyBuilder(HierarchyBuilder):
    key = "tis-team-hierarchy"
    title = "TIS 团队层级图"
    description = "以组织架构层级图展示 TIS 风险管理团队的层级与隶属关系（仅 TIS 类）"
    business_types = ["tis"]
    filename_pattern = "{project_name}_TIS团队层级图.docx"
    default_title = "TIS 风险管理团队层级图"
    label_header = "角色/岗位"


__all__ = ["OrgHierarchyBuilder", "TisTeamHierarchyBuilder"]
