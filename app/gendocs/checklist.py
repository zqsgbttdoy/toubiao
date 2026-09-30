"""勾选类附件生成器（P0 批次 1B）：无行贿犯罪声明 + 企业资质清单勾选。

复用两套引擎：
- DeclarationBuilder（段落引擎 + 勾选项）→ 无行贿犯罪/无重大违法记录声明
- ColumnBuilder（列式引擎 + bool 勾选列）→ 企业资质证明文件清单
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .checklist_kit import BOX_CHECKED  # noqa: F401  (供阅读/断言引用)
from .column_kit import Column, ColumnBuilder
from .letters import DeclarationBuilder, LetterPayload


# ─────────────────────── 1. 无行贿犯罪 / 无重大违法记录声明 ───────────────────────

class NoBriberyPayload(LetterPayload):
    no_bribery_crime: bool = Field(default=True, description="近三年内无行贿犯罪记录")
    no_major_violation: bool = Field(default=True, description="近三年内无重大违法记录")
    no_dishonest_record: bool = Field(default=True, description="未被列为失信被执行人 / 严重违法失信企业")
    situation_desc: str = Field(default="", max_length=500, description="需补充说明的情况（可留空）")


class NoBriberyDeclarationBuilder(DeclarationBuilder):
    key = "no-bribery-declaration"
    title = "无行贿犯罪 / 无重大违法记录声明"
    description = "以勾选方式郑重声明近三年无行贿犯罪、无重大违法及失信记录"
    business_types = ["supervision", "tis"]
    filename_pattern = "{project_name}_无行贿犯罪声明.docx"
    payload_model = NoBriberyPayload
    attachment_title = "无行贿犯罪记录及无重大违法记录声明"
    greeting = "致：{{tenderer_name}}"
    intro = (
        "我方 {{bidder_name}} 自愿参加 {{project_name}} 的投标活动。经自查，现郑重声明如下：",
    )
    check_items = (
        ("近三年内，我方及拟投入本项目的主要人员在经营活动中无行贿犯罪记录。", "no_bribery_crime"),
        ("近三年内，我方在经营活动中无重大违法记录，未因违法经营受到刑事处罚或责令停产停业、吊销许可证等行政处罚。", "no_major_violation"),
        ("我方未被人民法院列为失信被执行人，未被工商行政管理机关列入严重违法失信企业名单。", "no_dishonest_record"),
    )
    closing = "我方对上述声明内容的真实性负责。如有虚假，愿承担由此产生的一切法律责任并接受相应处理。特此声明。"
    sign_lines = (
        "投标人（盖章）：{{bidder_name}}",
        "法定代表人（签字）：＿＿＿＿＿＿＿",
        "日期：{{sign_date}}",
    )


# ─────────────────────────── 2. 企业资质证明文件清单 ───────────────────────────

class QualificationRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100, description="资质证明文件名称")
    provided: bool = Field(default=True, description="是否提供")
    copies: int = Field(default=1, ge=1, le=999, description="份数")
    doc_form: Literal["original", "copy"] = Field(default="copy", description="原件或复印件")
    remark: str = Field(default="", max_length=200, description="备注")


class QualificationChecklistPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: list[QualificationRow] = Field(min_length=1, max_length=100)
    title: str = Field(default="企业资质证明文件清单", max_length=200)


class QualificationChecklistBuilder(ColumnBuilder):
    key = "qualification-checklist"
    title = "企业资质证明文件清单"
    description = "以勾选方式列示拟提交的资质证书、营业执照等证明文件及份数"
    business_types = ["supervision", "tis"]
    filename_pattern = "{project_name}_资质证明文件清单.docx"
    payload_model = QualificationChecklistPayload
    default_title = "企业资质证明文件清单"
    notice = "本清单由软件自动生成，勾选状态与份数须人工核对；正式提交时请按清单逐一附证并加盖公章。"
    columns = (
        Column("name", "资质 / 证明文件名称", width_cm=5.2, type="text", required=True, max_length=100),
        Column("provided", "是否提供", width_cm=1.8, type="bool"),
        Column("copies", "份数", width_cm=1.6, type="number", align="center"),
        Column("doc_form", "原件/复印件", width_cm=2.6, type="select",
               options={"original": "原件", "copy": "复印件"}),
        Column("remark", "备注", width_cm=3.4, type="text", max_length=200),
    )
