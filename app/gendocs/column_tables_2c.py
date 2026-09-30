"""列式表格附件生成器（P1 批次 2C）：直接复用通用列式引擎，仅声明列定义。

办公设施表(#25) / TIS检测设备表(#26) / 旁站监理方案表(#30) / 见证取样送检计划表(#31) /
风险分级标准表(#32) / 报告制度及时效表(#33) / 财务证明近三年审计(#34)。
每个生成器 = 一组 Column + 一个 Pydantic 模型，零渲染代码（复用 ColumnBuilder）。
列宽合计超页面可用宽度时由 column_kit.scale_to_fit 自动缩放，防打印溢出。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .column_kit import Column, ColumnBuilder


class _Rows(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="", max_length=200)


# ═══════════════════ 1. 拟投入办公设施与交通工具表（#25）═══════════════════

class OfficeFacilityRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80, description="设施/设备名称")
    category: Literal["office", "vehicle", "comm", "living"] = Field(default="office", description="类别")
    spec: str = Field(default="", max_length=80, description="规格型号")
    quantity: int | None = Field(default=None, ge=1, le=9999, description="数量")
    unit: str = Field(default="", max_length=10, description="单位")
    purpose: str = Field(default="", max_length=120, description="用途")
    arrival: str = Field(default="", max_length=40, description="计划到位时间")
    remark: str = Field(default="", max_length=120, description="备注")


class OfficeFacilityPayload(_Rows):
    rows: list[OfficeFacilityRow] = Field(min_length=1, max_length=200)


class OfficeFacilitiesBuilder(ColumnBuilder):
    key = "office-facilities"
    title = "拟投入办公设施与交通工具表"
    description = "列示拟投入本项目的办公设备、交通工具、通讯与生活设施"
    business_types = ["supervision", "tis"]
    filename_pattern = "{project_name}_办公设施与交通工具表.docx"
    payload_model = OfficeFacilityPayload
    default_title = "拟投入办公设施与交通工具表"
    landscape = True
    columns = (
        Column("name", "设施/设备名称", 3.2, "left", "text", required=True),
        Column("category", "类别", 1.8, "center", "select",
               options={"office": "办公设备", "vehicle": "交通工具", "comm": "通讯设备", "living": "生活设施"}),
        Column("spec", "规格型号", 2.6, "left", "text"),
        Column("quantity", "数量", 1.2, "center", "number"),
        Column("unit", "单位", 1.2, "center", "text"),
        Column("purpose", "用途", 3.2, "left", "text"),
        Column("arrival", "计划到位时间", 2.2, "center", "text"),
        Column("remark", "备注", 3.0, "left", "text"),
    )


# ═══════════════════ 2. TIS 专用检测设备表（#26，仅 TIS）═══════════════════

class TisEquipmentRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80, description="检测设备名称")
    model_spec: str = Field(default="", max_length=80, description="型号规格")
    detection_use: str = Field(default="", max_length=150, description="检测用途/对象")
    quantity: int | None = Field(default=None, ge=1, le=9999, description="数量")
    unit: str = Field(default="", max_length=10, description="单位")
    precision: str = Field(default="", max_length=80, description="技术指标/精度")
    calibration: str = Field(default="", max_length=40, description="检定校准有效期")
    source: Literal["own", "rent"] = Field(default="own", description="设备来源")


class TisEquipmentPayload(_Rows):
    rows: list[TisEquipmentRow] = Field(min_length=1, max_length=200)


class TisEquipmentBuilder(ColumnBuilder):
    key = "tis-detection-equipment"
    title = "TIS 专用检测设备表"
    description = "列示 TIS 内窥镜/X光/红外成像/无人机等专用检测设备及检定状态（仅 TIS 类）"
    business_types = ["tis"]
    filename_pattern = "{project_name}_TIS检测设备表.docx"
    payload_model = TisEquipmentPayload
    default_title = "拟投入TIS专用检测设备表"
    landscape = True
    columns = (
        Column("name", "检测设备名称", 2.8, "left", "text", required=True),
        Column("model_spec", "型号规格", 2.2, "left", "text"),
        Column("detection_use", "检测用途/对象", 3.4, "left", "text"),
        Column("quantity", "数量", 1.0, "center", "number"),
        Column("unit", "单位", 1.0, "center", "text"),
        Column("precision", "技术指标/精度", 2.4, "left", "text"),
        Column("calibration", "检定有效期", 1.8, "center", "text"),
        Column("source", "来源", 1.4, "center", "select", options={"own": "自有", "rent": "租赁"}),
    )


# ═══════════════════ 3. 关键工序旁站监理方案表（#30，监理类）═══════════════════

class WitnessRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    process: str = Field(min_length=1, max_length=80, description="关键工序/部位")
    location: str = Field(default="", max_length=80, description="施工部位")
    content: str = Field(default="", max_length=200, description="旁站监理内容")
    key_points: str = Field(default="", max_length=200, description="质量控制要点")
    personnel: str = Field(default="", max_length=60, description="旁站人员")
    records: str = Field(default="", max_length=120, description="记录表单要求")


class WitnessPayload(_Rows):
    rows: list[WitnessRow] = Field(min_length=1, max_length=200)


class WitnessPlanBuilder(ColumnBuilder):
    key = "witness-plan"
    title = "关键工序旁站监理方案表"
    description = "明确关键工序/部位的旁站监理内容、控制要点、人员与记录要求（监理类）"
    business_types = ["supervision"]
    filename_pattern = "{project_name}_旁站监理方案表.docx"
    payload_model = WitnessPayload
    default_title = "关键工序旁站监理方案表"
    body_size_pt = 9
    columns = (
        Column("process", "关键工序/部位", 2.4, "left", "text", required=True),
        Column("location", "施工部位", 1.8, "left", "text"),
        Column("content", "旁站监理内容", 3.2, "left", "text"),
        Column("key_points", "质量控制要点", 3.2, "left", "text"),
        Column("personnel", "旁站人员", 1.4, "center", "text"),
        Column("records", "记录表单要求", 2.6, "left", "text"),
    )


# ═══════════════════ 4. 见证取样送检计划表（#31，监理类）═══════════════════

class SamplingRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    material: str = Field(min_length=1, max_length=80, description="材料/试件名称")
    test_item: str = Field(default="", max_length=100, description="检验/试验项目")
    frequency: str = Field(default="", max_length=80, description="取样批次/频次")
    quantity: str = Field(default="", max_length=40, description="取样数量")
    location: str = Field(default="", max_length=60, description="取样部位")
    lab: str = Field(default="", max_length=80, description="送检检测机构")
    standard: str = Field(default="", max_length=80, description="依据标准")


class SamplingPayload(_Rows):
    rows: list[SamplingRow] = Field(min_length=1, max_length=200)


class SamplingPlanBuilder(ColumnBuilder):
    key = "sampling-plan"
    title = "见证取样送检计划表"
    description = "按材料/试件列示见证取样的检验项目、频次、送检机构与依据标准（监理类）"
    business_types = ["supervision"]
    filename_pattern = "{project_name}_见证取样送检计划表.docx"
    payload_model = SamplingPayload
    default_title = "见证取样送检计划表"
    landscape = True
    body_size_pt = 9
    columns = (
        Column("material", "材料/试件名称", 2.6, "left", "text", required=True),
        Column("test_item", "检验/试验项目", 2.8, "left", "text"),
        Column("frequency", "取样批次/频次", 2.2, "center", "text"),
        Column("quantity", "取样数量", 1.4, "center", "text"),
        Column("location", "取样部位", 2.0, "left", "text"),
        Column("lab", "送检检测机构", 2.8, "left", "text"),
        Column("standard", "依据标准", 2.6, "left", "text"),
    )


# ═══════════════════ 5. 风险分级标准表（#32，三级）═══════════════════

class RiskGradeRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    level: str = Field(min_length=1, max_length=40, description="风险等级")
    criteria: str = Field(default="", max_length=250, description="分级判定标准")
    consequence: str = Field(default="", max_length=200, description="后果程度")
    control: str = Field(default="", max_length=200, description="管控层级/措施")
    deadline: str = Field(default="", max_length=80, description="处理/报告时限")


class RiskGradePayload(_Rows):
    rows: list[RiskGradeRow] = Field(min_length=1, max_length=60)


class RiskGradeStandardBuilder(ColumnBuilder):
    key = "risk-grade-standard"
    title = "风险分级标准表"
    description = "以三级（严重/重大/一般）界定风险判定标准、后果与管控响应"
    business_types = ["supervision", "tis"]
    filename_pattern = "{project_name}_风险分级标准表.docx"
    payload_model = RiskGradePayload
    default_title = "风险分级标准表"
    body_size_pt = 9
    columns = (
        Column("level", "风险等级", 1.6, "center", "text", required=True),
        Column("criteria", "分级判定标准", 4.2, "left", "text"),
        Column("consequence", "后果程度", 3.0, "left", "text"),
        Column("control", "管控层级/措施", 3.4, "left", "text"),
        Column("deadline", "处理/报告时限", 1.8, "center", "text"),
    )


# ═══════════════════ 6. 报告制度及时效表（#33，6 类）═══════════════════

class ReportTimelinessRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_type: str = Field(min_length=1, max_length=60, description="报告类别")
    trigger: str = Field(default="", max_length=200, description="适用情形/触发条件")
    author: str = Field(default="", max_length=60, description="编制/提交人")
    recipient: str = Field(default="", max_length=80, description="报送对象")
    deadline: str = Field(default="", max_length=80, description="提交时限")
    form: str = Field(default="", max_length=80, description="格式与份数")


class ReportTimelinessPayload(_Rows):
    rows: list[ReportTimelinessRow] = Field(min_length=1, max_length=60)


class ReportTimelinessBuilder(ColumnBuilder):
    key = "report-timeliness"
    title = "报告制度及时效表"
    description = "列示各类监理/TIS 报告的适用情形、报送对象与时限（TIS 强制时效）"
    business_types = ["supervision", "tis"]
    filename_pattern = "{project_name}_报告制度及时效表.docx"
    payload_model = ReportTimelinessPayload
    default_title = "报告制度及时效表"
    columns = (
        Column("report_type", "报告类别", 2.0, "center", "text", required=True),
        Column("trigger", "适用情形/触发条件", 3.6, "left", "text"),
        Column("author", "编制人", 1.4, "center", "text"),
        Column("recipient", "报送对象", 2.0, "left", "text"),
        Column("deadline", "提交时限", 1.6, "center", "text"),
        Column("form", "格式与份数", 1.6, "center", "text"),
    )


# ═══════════════════ 7. 财务证明·近三年审计（#34）═══════════════════

class FinanceRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    year: str = Field(min_length=1, max_length=20, description="财务年度")
    revenue: str = Field(default="", max_length=40, description="营业收入(元)")
    net_profit: str = Field(default="", max_length=40, description="净利润(元)")
    total_assets: str = Field(default="", max_length=40, description="资产总额(元)")
    liability: str = Field(default="", max_length=40, description="负债总额(元)")
    auditor: str = Field(default="", max_length=80, description="审计机构")
    opinion: str = Field(default="", max_length=80, description="审计意见类型")


class FinancePayload(_Rows):
    rows: list[FinanceRow] = Field(min_length=1, max_length=20)


class FinanceProofBuilder(ColumnBuilder):
    key = "finance-proof"
    title = "财务证明（近三年审计）"
    description = "近三年营业收入、利润、资产负债及审计机构与意见的财务证明表"
    business_types = ["supervision", "tis"]
    filename_pattern = "{project_name}_财务证明.docx"
    payload_model = FinancePayload
    default_title = "近三年财务状况表"
    landscape = True
    columns = (
        Column("year", "财务年度", 1.6, "center", "text", required=True),
        Column("revenue", "营业收入(元)", 2.6, "right", "number", money=True),
        Column("net_profit", "净利润(元)", 2.4, "right", "number", money=True),
        Column("total_assets", "资产总额(元)", 2.6, "right", "number", money=True),
        Column("liability", "负债总额(元)", 2.6, "right", "number", money=True),
        Column("auditor", "审计机构", 2.8, "left", "text"),
        Column("opinion", "审计意见", 2.2, "center", "text"),
    )


C2C_BUILDERS = (
    OfficeFacilitiesBuilder(), TisEquipmentBuilder(), WitnessPlanBuilder(),
    SamplingPlanBuilder(), RiskGradeStandardBuilder(), ReportTimelinessBuilder(),
    FinanceProofBuilder(),
)

__all__ = [
    "OfficeFacilitiesBuilder", "TisEquipmentBuilder", "WitnessPlanBuilder",
    "SamplingPlanBuilder", "RiskGradeStandardBuilder", "ReportTimelinessBuilder",
    "FinanceProofBuilder", "C2C_BUILDERS",
]
