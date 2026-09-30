"""列式表格附件生成器（P0 批次 1D）：直接复用通用引擎，仅声明列定义。

商务偏离表 / 技术偏离表 / 风险识别清单 / TIS检查节点计划表 / TIS风险管理团队配置表。
每个生成器 = 一组 Column + 一个 Pydantic 模型，零渲染代码（复用 ColumnBuilder）。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .column_kit import Column, ColumnBuilder

DEVIATION_OPTIONS = {"none": "无偏离", "positive": "正偏离", "negative": "负偏离"}


class _Rows(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="", max_length=200)


# ═══════════════════ 1. 商务偏离表（6 列）═══════════════════

class CommercialDeviationRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    clause: str = Field(min_length=1, max_length=50, description="招标文件条款号")
    clause_name: str = Field(default="", max_length=100, description="条款名称")
    bid_response: str = Field(default="", max_length=300, description="投标响应内容")
    deviation: Literal["none", "positive", "negative"] = Field(default="none", description="偏离情况")
    remark: str = Field(default="", max_length=300, description="说明及措施")


class CommercialDeviationPayload(_Rows):
    rows: list[CommercialDeviationRow] = Field(min_length=1, max_length=200)


class CommercialDeviationBuilder(ColumnBuilder):
    key = "commercial-deviation"
    title = "商务偏离表"
    description = "逐条响应招标文件商务条款并标注无偏离/正偏离/负偏离"
    business_types = ["supervision", "tis"]
    filename_pattern = "{project_name}_商务偏离表.docx"
    payload_model = CommercialDeviationPayload
    default_title = "商务偏离表"
    columns = (
        Column("clause", "条款号", 1.8, "center", "text", required=True),
        Column("clause_name", "条款名称", 3.0, "left", "text"),
        Column("bid_response", "投标响应内容", 4.0, "left", "text"),
        Column("deviation", "偏离情况", 1.8, "center", "select", options=DEVIATION_OPTIONS),
        Column("remark", "说明及措施", 4.0, "left", "text"),
    )


# ═══════════════════ 2. 技术偏离表（5 列）═══════════════════

class TechnicalDeviationRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    clause: str = Field(min_length=1, max_length=80, description="技术条款/参数项")
    tender_requirement: str = Field(default="", max_length=300, description="招标技术要求")
    bid_response: str = Field(default="", max_length=300, description="投标技术方案")
    deviation: Literal["none", "positive", "negative"] = Field(default="none", description="偏离情况")


class TechnicalDeviationPayload(_Rows):
    rows: list[TechnicalDeviationRow] = Field(min_length=1, max_length=200)


class TechnicalDeviationBuilder(ColumnBuilder):
    key = "technical-deviation"
    title = "技术偏离表"
    description = "逐条对照招标技术要求与投标方案，标注偏离情况"
    business_types = ["supervision", "tis"]
    filename_pattern = "{project_name}_技术偏离表.docx"
    payload_model = TechnicalDeviationPayload
    default_title = "技术偏离表"
    columns = (
        Column("clause", "技术条款/参数", 2.6, "left", "text", required=True),
        Column("tender_requirement", "招标技术要求", 4.2, "left", "text"),
        Column("bid_response", "投标技术方案", 4.2, "left", "text"),
        Column("deviation", "偏离情况", 1.8, "center", "select", options=DEVIATION_OPTIONS),
    )


# ═══════════════════ 3. 风险识别清单（8 列）═══════════════════

class RiskRegisterRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str = Field(min_length=1, max_length=50, description="风险类别")
    location: str = Field(default="", max_length=80, description="风险部位/环节")
    description: str = Field(default="", max_length=300, description="风险描述")
    level: Literal["extreme", "high", "medium", "low"] = Field(default="medium", description="风险等级")
    consequence: str = Field(default="", max_length=200, description="可能后果")
    measure: str = Field(default="", max_length=300, description="防范及应对措施")
    responsible: str = Field(default="", max_length=60, description="责任人/完成期限")


class RiskRegisterPayload(_Rows):
    rows: list[RiskRegisterRow] = Field(min_length=1, max_length=200)


class RiskRegisterBuilder(ColumnBuilder):
    key = "risk-register"
    title = "风险识别清单"
    description = "识别—分级—措施—责任闭环的风险清单，等级取极高/高/中/低"
    business_types = ["supervision", "tis"]
    filename_pattern = "{project_name}_风险识别清单.docx"
    payload_model = RiskRegisterPayload
    default_title = "风险识别清单"
    body_size_pt = 9
    header_size_pt = 9
    columns = (
        Column("category", "风险类别", 1.8, "center", "text", required=True),
        Column("location", "部位/环节", 2.4, "center", "text"),
        Column("description", "风险描述", 3.2, "left", "text"),
        Column("level", "等级", 1.2, "center", "select",
               options={"extreme": "极高", "high": "高", "medium": "中", "low": "低"}),
        Column("consequence", "可能后果", 2.6, "left", "text"),
        Column("measure", "应对措施", 3.4, "left", "text"),
        Column("responsible", "责任人/期限", 1.8, "center", "text"),
    )


# ═══════════════════ 4. TIS 检查节点计划表（7 列）═══════════════════

class InspectionNodeRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node: str = Field(min_length=1, max_length=80, description="检查节点名称")
    phase: str = Field(default="", max_length=40, description="检查阶段")
    timing: str = Field(default="", max_length=60, description="计划检查时点")
    content: str = Field(default="", max_length=300, description="检查内容")
    method: str = Field(default="", max_length=200, description="检查方式/依据")
    personnel: str = Field(default="", max_length=80, description="检查人员/专业")


class InspectionNodePayload(_Rows):
    rows: list[InspectionNodeRow] = Field(min_length=1, max_length=60)


class TisInspectionNodeBuilder(ColumnBuilder):
    key = "tis-inspection-nodes"
    title = "TIS 检查节点计划表"
    description = "按设计/施工/竣工等关键必检节点排定检查内容与人员（仅 TIS 类）"
    business_types = ["tis"]
    filename_pattern = "{project_name}_TIS检查节点计划表.docx"
    payload_model = InspectionNodePayload
    default_title = "TIS 风险检查节点计划表"
    body_size_pt = 9
    columns = (
        Column("node", "检查节点", 2.4, "center", "text", required=True),
        Column("phase", "检查阶段", 1.6, "center", "text"),
        Column("timing", "计划时点", 2.0, "center", "text"),
        Column("content", "检查内容", 3.6, "left", "text"),
        Column("method", "检查方式/依据", 2.2, "left", "text"),
        Column("personnel", "检查人员/专业", 1.8, "center", "text"),
    )


# ═══════════════════ 5. TIS 风险管理团队配置表（混合，取列表版式）═══════════════════

class TisTeamRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str = Field(min_length=1, max_length=50, description="岗位角色")
    name: str = Field(default="", max_length=50, description="姓名")
    title_level: str = Field(default="", max_length=50, description="职称")
    qualification: str = Field(default="", max_length=100, description="注册执业资格")
    experience_years: int | None = Field(default=None, ge=0, le=60, description="从业年限")
    major: str = Field(default="", max_length=50, description="专业方向")
    onsite_plan: str = Field(default="", max_length=100, description="到场安排/投入占比")


class TisTeamPayload(_Rows):
    rows: list[TisTeamRow] = Field(min_length=1, max_length=60)


class TisTeamConfigBuilder(ColumnBuilder):
    key = "tis-team-config"
    title = "TIS 风险管理团队配置表"
    description = "列示 TIS 风险管理团队各岗位人员资格、年限与到场安排（仅 TIS 类）"
    business_types = ["tis"]
    filename_pattern = "{project_name}_TIS团队配置表.docx"
    payload_model = TisTeamPayload
    default_title = "项目风险管理团队配置表"
    columns = (
        Column("role", "岗位角色", 2.0, "center", "text", required=True),
        Column("name", "姓名", 1.6, "center", "text"),
        Column("title_level", "职称", 1.6, "center", "text"),
        Column("qualification", "注册执业资格", 2.2, "left", "text"),
        Column("experience_years", "从业年限", 1.0, "center", "number"),
        Column("major", "专业方向", 1.6, "center", "text"),
        Column("onsite_plan", "到场安排/占比", 2.0, "left", "text"),
    )
