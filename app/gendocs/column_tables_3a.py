"""列式表格附件生成器（P2 批次 3A）：直接复用通用列式引擎，仅声明列定义。

监理工作制度清单(#36) / 监理实施细则清单(#37) / IDI平台上传责任分工表(#39) /
拟投入主要材料计划表(#40)。每个生成器 = 一组 Column + 一个 Pydantic 模型，零渲染代码。
列宽合计超页面可用宽度时由 column_kit.scale_to_fit 自动缩放，防打印溢出。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .column_kit import Column, ColumnBuilder


class _Rows(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="", max_length=200)


# ═══════════════════ 1. 监理工作制度清单（#36，监理类）═══════════════════

class SupervisionSystemRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: Literal["contract", "quality", "safety", "progress", "cost", "internal"] = Field(
        default="quality", description="制度类别")
    name: str = Field(min_length=1, max_length=80, description="制度名称")
    content: str = Field(default="", max_length=300, description="主要内容 / 工作要求")
    scope: str = Field(default="", max_length=120, description="适用岗位与范围")
    records: str = Field(default="", max_length=120, description="配套记录表单/台账")


class SupervisionSystemPayload(_Rows):
    rows: list[SupervisionSystemRow] = Field(min_length=1, max_length=100)


class SupervisionSystemBuilder(ColumnBuilder):
    key = "supervision-systems"
    title = "监理工作制度清单"
    description = "按合同/质量/安全/进度/造价/内部管理类列举项目监理机构的工作制度及表单（监理类）"
    business_types = ["supervision"]
    filename_pattern = "{project_name}_监理工作制度清单.docx"
    payload_model = SupervisionSystemPayload
    default_title = "监理工作制度清单"
    body_size_pt = 9
    columns = (
        Column("category", "制度类别", 1.8, "center", "select",
               options={"contract": "合同管理", "quality": "质量控制", "safety": "安全生产",
                        "progress": "进度控制", "cost": "造价控制", "internal": "内部管理"}),
        Column("name", "制度名称", 2.6, "left", "text", required=True),
        Column("content", "主要内容/工作要求", 4.6, "left", "text", max_length=300),
        Column("scope", "适用岗位与范围", 2.4, "left", "text"),
        Column("records", "配套记录表单/台账", 2.6, "left", "text"),
    )


# ═══════════════════ 2. 监理实施细则清单（#37，监理类）═══════════════════

class SupervisionRuleRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    area: str = Field(min_length=1, max_length=80, description="专业/部位")
    rule_name: str = Field(default="", max_length=100, description="实施细则名称")
    standard: str = Field(default="", max_length=150, description="执行依据/标准")
    method: str = Field(default="", max_length=100, description="监理方式(平行/巡检/旁站等)")
    control_points: str = Field(default="", max_length=300, description="质量控制要点/工序")
    author: str = Field(default="", max_length=60, description="编制/批准")


class SupervisionRulePayload(_Rows):
    rows: list[SupervisionRuleRow] = Field(min_length=1, max_length=100)


class SupervisionRuleListBuilder(ColumnBuilder):
    key = "supervision-rules"
    title = "监理实施细则清单"
    description = "按专业/部位列示监理实施细则的执行依据、监理方式与质量控制要点（监理类）"
    business_types = ["supervision"]
    filename_pattern = "{project_name}_监理实施细则清单.docx"
    payload_model = SupervisionRulePayload
    default_title = "监理实施细则清单"
    landscape = True
    body_size_pt = 9
    columns = (
        Column("area", "专业/部位", 2.4, "left", "text", required=True),
        Column("rule_name", "实施细则名称", 2.8, "left", "text"),
        Column("standard", "执行依据/标准", 2.8, "left", "text"),
        Column("method", "监理方式", 2.0, "center", "text"),
        Column("control_points", "质量控制要点/工序", 5.2, "left", "text", max_length=300),
        Column("author", "编制/批准", 1.8, "center", "text"),
    )


# ═══════════════════ 3. IDI 平台上传责任分工表（#39，仅 TIS）═══════════════════

class IdiUploadRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node: str = Field(min_length=1, max_length=80, description="上传节点/阶段")
    content: str = Field(default="", max_length=200, description="上传内容")
    duty: Literal["lead", "check", "assist"] = Field(default="lead", description="责任类型")
    owner: str = Field(default="", max_length=60, description="责任人/岗位")
    deadline: str = Field(default="", max_length=80, description="上传时限")
    remark: str = Field(default="", max_length=120, description="备注")


class IdiUploadPayload(_Rows):
    rows: list[IdiUploadRow] = Field(min_length=1, max_length=100)


class IdiUploadDutyBuilder(ColumnBuilder):
    key = "idi-upload-duty"
    title = "IDI 平台上传责任分工表"
    description = "明确 IDI/质量缺陷保险平台各上传节点的内容、责任类型、责任人与时限（仅 TIS 类）"
    business_types = ["tis"]
    filename_pattern = "{project_name}_IDI平台上传分工表.docx"
    payload_model = IdiUploadPayload
    default_title = "IDI平台信息上传责任分工表"
    columns = (
        Column("node", "上传节点/阶段", 2.2, "left", "text", required=True),
        Column("content", "上传内容", 3.6, "left", "text", max_length=200),
        Column("duty", "责任类型", 1.6, "center", "select",
               options={"lead": "主报", "check": "审核确认", "assist": "配合协助"}),
        Column("owner", "责任人/岗位", 1.8, "center", "text"),
        Column("deadline", "上传时限", 1.6, "center", "text"),
        Column("remark", "备注", 2.2, "left", "text"),
    )


# ═══════════════════ 4. 拟投入主要材料计划表（#40，通用）═══════════════════

class MaterialPlanRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80, description="材料名称")
    spec: str = Field(default="", max_length=80, description="规格/型号")
    unit: str = Field(default="", max_length=10, description="单位")
    quantity: int | None = Field(default=None, ge=1, le=999999, description="计划数量")
    period: str = Field(default="", max_length=60, description="供应批次/时间")
    location: str = Field(default="", max_length=80, description="到场部位/地点")
    quality: str = Field(default="", max_length=150, description="质量要求/验收标准")
    remark: str = Field(default="", max_length=120, description="备注")


class MaterialPlanPayload(_Rows):
    rows: list[MaterialPlanRow] = Field(min_length=1, max_length=200)


class MaterialPlanBuilder(ColumnBuilder):
    key = "material-plan"
    title = "拟投入主要材料计划表"
    description = "按材料名称/规格列示计划数量、供应批次、到场部位与质量验收要求"
    business_types = ["supervision", "tis"]
    filename_pattern = "{project_name}_主要材料计划表.docx"
    payload_model = MaterialPlanPayload
    default_title = "拟投入主要材料计划表"
    landscape = True
    columns = (
        Column("name", "材料名称", 2.4, "left", "text", required=True),
        Column("spec", "规格/型号", 2.2, "left", "text"),
        Column("unit", "单位", 1.0, "center", "text"),
        Column("quantity", "计划数量", 1.4, "center", "number"),
        Column("period", "供应批次/时间", 2.0, "center", "text"),
        Column("location", "到场部位/地点", 2.2, "left", "text"),
        Column("quality", "质量要求/验收标准", 3.4, "left", "text", max_length=150),
        Column("remark", "备注", 2.2, "left", "text"),
    )


COLUMN_3A_BUILDERS = (
    SupervisionSystemBuilder(), SupervisionRuleListBuilder(),
    IdiUploadDutyBuilder(), MaterialPlanBuilder(),
)

__all__ = [
    "SupervisionSystemBuilder", "SupervisionRuleListBuilder",
    "IdiUploadDutyBuilder", "MaterialPlanBuilder", "COLUMN_3A_BUILDERS",
]
