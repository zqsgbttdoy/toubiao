"""列式表格附件生成器（P0 批次 1C）：含横向多列表与计算列。

全部基于通用引擎 ColumnBuilder，仅声明 Column 组合 + Pydantic 模型：
- 进退场登记表(横向16列/在场天数自动计算)、机构组成表、类似项目业绩表(横向19列)
- 商务报价明细表(小计计算列 + 合计行)、开标一览表(金额千分位)、人员证书一览表
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from docx.enum.text import WD_ALIGN_PARAGRAPH
from pydantic import BaseModel, ConfigDict, Field

from .column_kit import (TOTAL_FILL, Column, ColumnBuilder, diff_days, money)
from .docx_kit import set_cell_text, shade_cell


class _Rows(BaseModel):
    """所有表格类 payload 的公共外壳：rows + 可选 title。"""
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="", max_length=200)


# ═══════════════════ 1. 监理人员进退场登记表（横向 16 列 + 在场天数计算）═══════════════════

class StaffRegisterRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=50, description="姓名")
    role: str = Field(default="", max_length=50, description="岗位")
    title_level: str = Field(default="", max_length=50, description="职称")
    cert_no: str = Field(default="", max_length=64, description="注册/证书号")
    education: str = Field(default="", max_length=30, description="学历")
    major: str = Field(default="", max_length=50, description="专业")
    work_years: int | None = Field(default=None, ge=0, le=60, description="从业年限")
    entry_date: date | None = Field(default=None, description="进场日期")
    exit_date: date | None = Field(default=None, description="退场日期")
    phone: str = Field(default="", max_length=30, description="联系电话")
    id_card: str = Field(default="", max_length=32, description="身份证号")
    work_status: Literal["on_site", "off_site", "pending"] = Field(default="on_site", description="在场状态")
    handover: str = Field(default="", max_length=50, description="交接人")
    remark: str = Field(default="", max_length=200, description="备注")


class StaffRegisterPayload(_Rows):
    rows: list[StaffRegisterRow] = Field(min_length=1, max_length=120)


class StaffRegisterBuilder(ColumnBuilder):
    key = "staff-register"
    title = "监理人员进退场登记表"
    description = "横向 A4 多列表格，逐人登记进退场信息与在场天数（自动计算）"
    business_types = ["supervision", "tis"]
    filename_pattern = "{project_name}_人员进退场登记表.docx"
    payload_model = StaffRegisterPayload
    default_title = "监理人员进退场登记表"
    landscape = True
    body_size_pt = 8
    header_size_pt = 8
    columns = (
        Column("name", "姓名", 1.6, "center", "text", required=True, max_length=50),
        Column("role", "岗位", 1.6, "center", "text"),
        Column("title_level", "职称", 1.6, "center", "text"),
        Column("cert_no", "注册/证书号", 2.6, "center", "text"),
        Column("education", "学历", 1.0, "center", "text"),
        Column("major", "专业", 1.7, "left", "text"),
        Column("work_years", "从业年限", 1.0, "center", "number"),
        Column("entry_date", "进场日期", 1.8, "center", "date"),
        Column("exit_date", "退场日期", 1.8, "center", "date"),
        Column("on_site_days", "在场天数", 1.0, "center", "text", value_fn=lambda r: diff_days(r.entry_date, r.exit_date)),
        Column("phone", "联系电话", 2.3, "center", "text"),
        Column("id_card", "身份证号", 3.2, "center", "text"),
        Column("work_status", "在场状态", 1.1, "center", "select", options={"on_site": "在场", "off_site": "退场", "pending": "待定"}),
        Column("handover", "交接人", 1.6, "center", "text"),
        Column("remark", "备注", 2.2, "left", "text"),
    )


# ═══════════════════════════ 2. 项目监理机构组成表 ═══════════════════════════

class OrgMemberRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str = Field(min_length=1, max_length=50, description="岗位")
    name: str = Field(default="", max_length=50, description="姓名")
    gender: str = Field(default="", max_length=4, description="性别")
    age: int | None = Field(default=None, ge=18, le=80, description="年龄")
    title_level: str = Field(default="", max_length=50, description="职称")
    qualification: str = Field(default="", max_length=100, description="注册执业资格")
    major: str = Field(default="", max_length=50, description="专业")
    phone: str = Field(default="", max_length=30, description="联系方式")
    duty: str = Field(default="", max_length=200, description="本项目职责")


class OrgCompositionPayload(_Rows):
    rows: list[OrgMemberRow] = Field(min_length=1, max_length=80)


class OrgCompositionBuilder(ColumnBuilder):
    key = "org-composition"
    title = "项目监理机构组成表"
    description = "以列表形式登记项目监理机构各岗位人员及其资格与职责"
    business_types = ["supervision"]
    filename_pattern = "{project_name}_监理机构组成表.docx"
    payload_model = OrgCompositionPayload
    default_title = "项目监理机构组成表"
    columns = (
        Column("role", "岗位", 1.9, "center", "text", required=True),
        Column("name", "姓名", 1.6, "center", "text"),
        Column("gender", "性别", 1.0, "center", "select", options={"男": "男", "女": "女"}),
        Column("age", "年龄", 1.0, "center", "number"),
        Column("title_level", "职称", 1.8, "center", "text"),
        Column("qualification", "注册执业资格", 2.6, "left", "text"),
        Column("major", "专业", 1.7, "center", "text"),
        Column("phone", "联系方式", 2.2, "center", "text"),
        Column("duty", "本项目职责", 3.2, "left", "text"),
    )


# ═══════════════════ 3. 类似项目业绩表（横向 19 列）═══════════════════

class SimilarProjectRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120, description="项目名称")
    project_type: str = Field(default="", max_length=40, description="工程类别")
    scale: str = Field(default="", max_length=50, description="建设规模")
    structure_type: str = Field(default="", max_length=40, description="结构类型")
    contract_value: str = Field(default="", max_length=30, description="合同额(万元)")
    area: str = Field(default="", max_length=40, description="建筑面积(㎡)")
    span_length: str = Field(default="", max_length=40, description="长度/跨度/层数")
    our_role: str = Field(default="", max_length=40, description="我方角色")
    chief: str = Field(default="", max_length=40, description="总监理工程师")
    quality: str = Field(default="", max_length=60, description="质量等级/获奖")
    client: str = Field(default="", max_length=80, description="建设单位")
    client_contact: str = Field(default="", max_length=40, description="业主联系人")
    client_phone: str = Field(default="", max_length=30, description="联系电话")
    contract_date: str = Field(default="", max_length=20, description="合同签订日期")
    start_date: str = Field(default="", max_length=20, description="开工日期")
    complete_date: str = Field(default="", max_length=20, description="竣工日期")
    acceptance: Literal["passed", "pending"] = Field(default="passed", description="验收情况")
    region: str = Field(default="", max_length=50, description="项目所在地")


class SimilarProjectsPayload(_Rows):
    rows: list[SimilarProjectRow] = Field(min_length=1, max_length=80)


class SimilarProjectsBuilder(ColumnBuilder):
    key = "similar-projects"
    title = "类似项目业绩表"
    description = "横向 A4 多列，登记类似工程监理业绩（金额/日期/验收等）"
    business_types = ["supervision", "tis"]
    filename_pattern = "{project_name}_类似项目业绩表.docx"
    payload_model = SimilarProjectsPayload
    default_title = "类似项目业绩表"
    landscape = True
    body_size_pt = 7.5
    header_size_pt = 7.5
    columns = (
        Column("name", "项目名称", 2.8, "left", "text", required=True),
        Column("project_type", "工程类别", 1.3, "center", "text"),
        Column("scale", "建设规模", 1.4, "center", "text"),
        Column("structure_type", "结构类型", 1.3, "center", "text"),
        Column("contract_value", "合同额(万元)", 1.4, "right", "text"),
        Column("area", "建筑面积(㎡)", 1.4, "right", "text"),
        Column("span_length", "长度/层数", 1.3, "center", "text"),
        Column("our_role", "我方角色", 1.3, "center", "text"),
        Column("chief", "总监", 1.3, "center", "text"),
        Column("quality", "质量/获奖", 1.4, "left", "text"),
        Column("client", "建设单位", 2.0, "left", "text"),
        Column("client_contact", "联系人", 1.3, "center", "text"),
        Column("client_phone", "联系电话", 1.6, "center", "text"),
        Column("contract_date", "合同签订", 1.5, "center", "text"),
        Column("start_date", "开工", 1.5, "center", "text"),
        Column("complete_date", "竣工", 1.5, "center", "text"),
        Column("acceptance", "验收情况", 1.3, "center", "select", options={"passed": "已验收", "pending": "未验收"}),
        Column("region", "项目所在地", 1.5, "left", "text"),
    )


# ═══════════════════ 4. 商务报价明细表（小计计算列 + 合计行）═══════════════════

class QuoteDetailRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100, description="费用项目")
    spec: str = Field(default="", max_length=200, description="规格/说明")
    unit: str = Field(default="", max_length=20, description="单位")
    quantity: Decimal = Field(default=Decimal("0"), ge=0, description="数量")
    unit_price: Decimal = Field(default=Decimal("0"), ge=0, description="单价(元)")


class QuoteDetailPayload(_Rows):
    rows: list[QuoteDetailRow] = Field(min_length=1, max_length=200)


class QuotationDetailBuilder(ColumnBuilder):
    key = "quotation-detail"
    title = "商务报价明细表"
    description = "列示各费用项目数量与单价，自动计算小计并在末尾汇总合计金额"
    business_types = ["supervision", "tis"]
    filename_pattern = "{project_name}_报价明细表.docx"
    payload_model = QuoteDetailPayload
    default_title = "商务报价明细表"
    notice = "本表由软件自动计算小计与合计，权威报价金额以「商务报价」模块结论为准；打印前请人工核对。"
    columns = (
        Column("name", "费用项目", 4.0, "left", "text", required=True),
        Column("spec", "规格/说明", 3.2, "left", "text"),
        Column("unit", "单位", 1.4, "center", "text"),
        Column("quantity", "数量", 1.7, "right", "number"),
        Column("unit_price", "单价(元)", 2.0, "right", "number", money=True),
        Column("subtotal", "小计(元)", 2.4, "right", "text", value_fn=lambda r: money(r.quantity * r.unit_price)),
    )

    def add_footer_rows(self, payload, table, col_offset):
        total = sum((r.quantity * r.unit_price for r in payload.rows), Decimal("0"))
        row = table.add_row()
        cells = row.cells
        base = 1 if self.has_sequence else 0
        set_cell_text(cells[base], "合计", bold=True, size_pt=self.body_size_pt, align=WD_ALIGN_PARAGRAPH.CENTER)
        subtotal_index = base + 5  # subtotal 为第 6 个数据列
        set_cell_text(cells[subtotal_index], money(total), bold=True,
                      size_pt=self.body_size_pt, align=WD_ALIGN_PARAGRAPH.RIGHT)
        for cell in cells:
            shade_cell(cell, TOTAL_FILL)


# ═══════════════════ 5. 开标一览表 / 投标报价表（6 列）═══════════════════

class BidOpeningRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    section: str = Field(min_length=1, max_length=100, description="标段名称")
    total_price: Decimal = Field(default=Decimal("0"), ge=0, description="投标总价(元)")
    duration: str = Field(default="", max_length=60, description="服务期限")
    quality: str = Field(default="", max_length=60, description="质量目标")
    remark: str = Field(default="", max_length=200, description="备注")


class BidOpeningPayload(_Rows):
    rows: list[BidOpeningRow] = Field(min_length=1, max_length=50)


class BidOpeningTableBuilder(ColumnBuilder):
    key = "bid-opening"
    title = "开标一览表 / 投标报价表"
    description = "汇总各标段投标总价、服务期限与质量目标的开标表"
    business_types = ["supervision", "tis"]
    filename_pattern = "{project_name}_开标一览表.docx"
    payload_model = BidOpeningPayload
    default_title = "开标一览表"
    columns = (
        Column("section", "标段名称", 4.0, "left", "text", required=True),
        Column("total_price", "投标总价(元)", 3.2, "right", "number", money=True),
        Column("duration", "服务期限", 2.6, "center", "text"),
        Column("quality", "质量目标", 2.6, "center", "text"),
        Column("remark", "备注", 2.4, "left", "text"),
    )


# ═══════════════════ 6. 项目管理主要人员证书一览表（8 列）═══════════════════

class StaffCertRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=50, description="姓名")
    role: str = Field(default="", max_length=50, description="拟任岗位")
    title_level: str = Field(default="", max_length=50, description="职称/职务")
    cert_name: str = Field(default="", max_length=60, description="证书名称")
    cert_no: str = Field(default="", max_length=64, description="证书/注册号")
    expiry: str = Field(default="", max_length=30, description="有效期至")
    major: str = Field(default="", max_length=50, description="专业")


class StaffCertificatePayload(_Rows):
    rows: list[StaffCertRow] = Field(min_length=1, max_length=80)


class StaffCertificateBuilder(ColumnBuilder):
    key = "staff-certificate"
    title = "项目管理主要人员证书一览表"
    description = "登记拟投入主要人员的执业/职称证书、注册号与有效期"
    business_types = ["supervision"]
    filename_pattern = "{project_name}_人员证书一览表.docx"
    payload_model = StaffCertificatePayload
    default_title = "项目管理主要人员证书一览表"
    columns = (
        Column("name", "姓名", 1.7, "center", "text", required=True),
        Column("role", "拟任岗位", 2.0, "center", "text"),
        Column("title_level", "职称/职务", 2.0, "center", "text"),
        Column("cert_name", "证书名称", 2.4, "left", "text"),
        Column("cert_no", "证书/注册号", 2.6, "center", "text"),
        Column("expiry", "有效期至", 1.8, "center", "text"),
        Column("major", "专业", 1.9, "center", "text"),
    )
