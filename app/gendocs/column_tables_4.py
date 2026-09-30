"""列式表格附件生成器（P3 批次 4A + 4C）：直接复用通用列式引擎，仅声明列定义。

临时用地表(#43) / 拟分包项目情况表(#45) / 施工总平面布置说明表(#42)。
每个生成器 = 一组 Column + 一个 Pydantic 模型，零渲染代码（复用 ColumnBuilder）。
#42 因 CSP 禁外部绘图库、报告亦要求「只用表格模拟法，放弃真实形状」，
以功能分区说明表落地，并显式提示正式投标须另附按比例绘制的 CAD 平面图。
列宽合计超页面可用宽度时由 column_kit.scale_to_fit 自动缩放，防打印溢出。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .column_kit import Column, ColumnBuilder


class _Rows(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="", max_length=200)


# ═══════════════════ 1. 临时用地表（#43，商务）═══════════════════

class TemporaryLandRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    location: str = Field(min_length=1, max_length=80, description="具体位置/方位")
    use: str = Field(default="", max_length=80, description="用途")
    area: int | None = Field(default=None, ge=1, le=999999, description="占地面积(㎡)")
    land_type: Literal["farmland", "construction", "unused", "other"] = Field(
        default="construction", description="地类")
    period: str = Field(default="", max_length=60, description="使用期限")
    restore: str = Field(default="", max_length=150, description="使用结束后恢复方式")
    owner: str = Field(default="", max_length=80, description="权属人/协调情况")
    remark: str = Field(default="", max_length=120, description="备注")


class TemporaryLandPayload(_Rows):
    rows: list[TemporaryLandRow] = Field(min_length=1, max_length=100)


class TemporaryLandBuilder(ColumnBuilder):
    key = "temporary-land"
    title = "临时用地表"
    description = "列示项目所需临时用地的位置、用途、占地、地类、期限与到期恢复方式"
    business_types = ["supervision", "tis"]
    filename_pattern = "{project_name}_临时用地表.docx"
    payload_model = TemporaryLandPayload
    default_title = "临时用地表"
    landscape = True
    body_size_pt = 9
    columns = (
        Column("location", "具体位置/方位", 2.4, "left", "text", required=True),
        Column("use", "用途", 2.0, "left", "text"),
        Column("area", "占地面积(㎡)", 1.6, "center", "number"),
        Column("land_type", "地类", 1.6, "center", "select",
               options={"farmland": "耕地", "construction": "建设用地",
                        "unused": "未利用地", "other": "其他"}),
        Column("period", "使用期限", 2.0, "center", "text"),
        Column("restore", "到期恢复方式", 3.0, "left", "text", max_length=150),
        Column("owner", "权属人/协调", 2.2, "left", "text"),
        Column("remark", "备注", 2.0, "left", "text"),
    )


# ═══════════════════ 2. 拟分包项目情况表（#45，商务）═══════════════════

class SubcontractRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_name: str = Field(min_length=1, max_length=80, description="拟分包项目/部位")
    content: str = Field(default="", max_length=200, description="分包项目概况")
    reason: str = Field(default="", max_length=200, description="分包理由")
    subcontractor: str = Field(default="", max_length=80, description="拟分包单位名称")
    qualification: str = Field(default="", max_length=120, description="分包单位资质及等级")
    amount: str = Field(default="", max_length=40, description="分包金额(元)")
    ratio: str = Field(default="", max_length=20, description="占总价比例(%)")
    remark: str = Field(default="", max_length=120, description="备注")


class SubcontractPayload(_Rows):
    rows: list[SubcontractRow] = Field(min_length=1, max_length=100)


class SubcontractBuilder(ColumnBuilder):
    key = "subcontract-plan"
    title = "拟分包项目情况表"
    description = "列示拟分包的项目/部位、分包理由、分包单位资质、金额及占总价比例"
    business_types = ["supervision", "tis"]
    filename_pattern = "{project_name}_拟分包项目情况表.docx"
    payload_model = SubcontractPayload
    default_title = "拟分包项目情况表"
    landscape = True
    body_size_pt = 9
    columns = (
        Column("item_name", "拟分包项目/部位", 2.2, "left", "text", required=True),
        Column("content", "分包项目概况", 2.8, "left", "text", max_length=200),
        Column("reason", "分包理由", 2.8, "left", "text", max_length=200),
        Column("subcontractor", "拟分包单位", 2.2, "left", "text"),
        Column("qualification", "资质及等级", 2.4, "left", "text"),
        Column("amount", "分包金额(元)", 2.0, "right", "number", money=True),
        Column("ratio", "占总价(%)", 1.4, "center", "text"),
        Column("remark", "备注", 1.8, "left", "text"),
    )


# ═══════════════════ 3. 施工总平面布置说明表（#42，技术/降级为分区说明表）═══════════════════

class SiteLayoutRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    zone: str = Field(min_length=1, max_length=80, description="功能分区名称")
    position: str = Field(default="", max_length=120, description="相对建筑/场地方位")
    area: int | None = Field(default=None, ge=1, le=999999, description="占地面积(㎡)")
    facilities: str = Field(default="", max_length=200, description="主要临时设施/设备")
    duration: str = Field(default="", max_length=60, description="使用时间")
    safety: str = Field(default="", max_length=200, description="安全文明施工措施")
    access: str = Field(default="", max_length=120, description="出入口/运输通道")
    remark: str = Field(default="", max_length=120, description="备注")


class SiteLayoutPayload(_Rows):
    rows: list[SiteLayoutRow] = Field(min_length=1, max_length=100)


class SiteLayoutBuilder(ColumnBuilder):
    key = "site-layout"
    title = "施工总平面布置说明表"
    description = "以功能分区说明表呈现平面布置要点；正式投标须另附按比例绘制的施工总平面布置图"
    business_types = ["supervision", "tis"]
    filename_pattern = "{project_name}_施工总平面布置说明表.docx"
    payload_model = SiteLayoutPayload
    default_title = "施工总平面布置说明表"
    landscape = True
    body_size_pt = 9
    notice = ("本表由软件自动生成，为施工总平面布置的文字/表格说明；因图片须由项目技术负责人"
              "按现场实测与比例尺绘制（CAD/手绘扫描件），本表不含图形。正式投标文件请将绘制"
              "好的总平面布置图作为附图插入，并与本表分区口径保持一致，人工核对后方可提交。")
    columns = (
        Column("zone", "功能分区名称", 2.0, "left", "text", required=True),
        Column("position", "相对建筑/场地方位", 2.4, "left", "text", max_length=120),
        Column("area", "占地面积(㎡)", 1.6, "center", "number"),
        Column("facilities", "主要临时设施/设备", 3.0, "left", "text", max_length=200),
        Column("duration", "使用时间", 1.6, "center", "text"),
        Column("safety", "安全文明施工措施", 3.0, "left", "text", max_length=200),
        Column("access", "出入口/运输通道", 2.2, "left", "text", max_length=120),
        Column("remark", "备注", 1.6, "left", "text"),
    )


COLUMN_4_BUILDERS = (
    TemporaryLandBuilder(), SubcontractBuilder(), SiteLayoutBuilder(),
)

__all__ = [
    "TemporaryLandBuilder", "SubcontractBuilder", "SiteLayoutBuilder",
    "COLUMN_4_BUILDERS",
]
