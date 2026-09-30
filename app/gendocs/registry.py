"""附件生成器注册表：新增附件类型时在 _BUILDERS 追加实例即可。"""
from __future__ import annotations

from ..core import DomainError
from .bar_tables import ManpowerHistogramBuilder, ManpowerPlanBuilder
from .checklist import NoBriberyDeclarationBuilder, QualificationChecklistBuilder
from .column_tables import (BidOpeningTableBuilder, OrgCompositionBuilder,
                            QuotationDetailBuilder, SimilarProjectsBuilder,
                            StaffCertificateBuilder, StaffRegisterBuilder)
from .column_tables_1d import (CommercialDeviationBuilder, RiskRegisterBuilder,
                               TechnicalDeviationBuilder, TisInspectionNodeBuilder,
                               TisTeamConfigBuilder)
from .column_tables_2c import C2C_BUILDERS
from .column_tables_3a import COLUMN_3A_BUILDERS
from .column_tables_4 import COLUMN_4_BUILDERS
from .consortium import ConsortiumBuilder
from .equipment_list import EquipmentListBuilder
from .gantt_tables import ScheduleGanttBuilder, TisInspectionGanttBuilder
from .hierarchy import OrgHierarchyBuilder, TisTeamHierarchyBuilder
from .labor_plan import LaborPlanBuilder
from .letters import (AuthorizationBuilder, BidLetterBuilder,
                      ChiefSupervisorBuilder, CreditCommitmentBuilder,
                      LegalRepIdBuilder, TisIndependenceBuilder)
from .personnel_gantt import PersonnelGanttBuilder
from .rectification_flow import RectificationFlowBuilder
from .resume import SupervisorResumeBuilder
from .review_table import InternalReviewBuilder
from .sections import SupervisionOutlineBuilder, TisPlanBuilder

_BUILDERS = (
    PersonnelGanttBuilder(), EquipmentListBuilder(),
    # 段落类附件（P0 批次 1A）
    BidLetterBuilder(), LegalRepIdBuilder(), AuthorizationBuilder(),
    ChiefSupervisorBuilder(), TisIndependenceBuilder(), CreditCommitmentBuilder(),
    # 勾选类附件（P0 批次 1B）
    NoBriberyDeclarationBuilder(), QualificationChecklistBuilder(),
    # 列式扩展表格（P0 批次 1C）
    StaffRegisterBuilder(), OrgCompositionBuilder(), SimilarProjectsBuilder(),
    QuotationDetailBuilder(), BidOpeningTableBuilder(), StaffCertificateBuilder(),
    # 直接复用列式引擎的表格（P0 批次 1D）
    CommercialDeviationBuilder(), TechnicalDeviationBuilder(), RiskRegisterBuilder(),
    TisInspectionNodeBuilder(), TisTeamConfigBuilder(),
    # 章节类附件（P0 批次 1E）
    SupervisionOutlineBuilder(), TisPlanBuilder(),
    # 甘特横道图复用（P1 批次 2A）
    ScheduleGanttBuilder(), TisInspectionGanttBuilder(),
    # 柱状图引擎（P1 批次 2B）
    ManpowerPlanBuilder(), ManpowerHistogramBuilder(),
    # 列式引擎直接复用（P1 批次 2C，共 7 表）
    *C2C_BUILDERS,
    # 履历版式引擎（P1 批次 2D）
    SupervisorResumeBuilder(),
    # 层级图引擎（P1 批次 2E）
    OrgHierarchyBuilder(), TisTeamHierarchyBuilder(),
    # 内部复核表（三签，P1 批次 2F）
    InternalReviewBuilder(),
    # 列式引擎直接复用（P2 批次 3A，共 4 表）
    *COLUMN_3A_BUILDERS,
    # 层级图引擎流程形态（P2 批次 3B）
    RectificationFlowBuilder(),
    # 柱状图引擎人数加权（P2 批次 3C）
    LaborPlanBuilder(),
    # 列式引擎直接复用 + 平面布置降级说明表（P3 批次 4A+4C，共 3 表）
    *COLUMN_4_BUILDERS,
    # 段落引擎多方签署（P3 批次 4B）
    ConsortiumBuilder(),
)
REGISTRY = {b.key: b for b in _BUILDERS}


def get_builder(key: str):
    builder = REGISTRY.get(key)
    if not builder:
        raise DomainError("GENDOC_TEMPLATE_UNKNOWN", f"不支持的附件模板：{key}", 404)
    return builder


def list_builders(business_type: str | None = None):
    items = []
    for builder in _BUILDERS:
        if business_type and business_type not in builder.business_types:
            continue
        entry = {"key": builder.key, "title": builder.title,
                 "description": builder.description,
                 "business_types": builder.business_types,
                 "form_type": getattr(builder, "form_type", "table")}
        fields = getattr(builder, "form_fields", None)
        if callable(fields) and fields():
            entry["fields"] = fields()
        columns = getattr(builder, "columns_meta", None)
        if callable(columns) and columns():
            entry["columns"] = columns()
        items.append(entry)
    return items

