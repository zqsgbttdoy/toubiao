"""内部复核表（P1 批次 2F）：复用列式引擎的勾选/选择能力，追加三签复核栏。

投标文件内部复核表（#35，三签）——主体为「复核项目 × 结论」清单（结论取 符合/不符合/不适用
的 select 列，渲染同 ☑/□ 类勾选引擎风格），表格末尾以合并整行追加「复核结论 + 编制/复核/
审核批准」三级签署栏，满足内部质量记录的三签要求。渲染主体完全复用 ColumnBuilder。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .column_kit import Column, ColumnBuilder
from .docx_kit import set_cell_text

RESULT_OPTIONS = {"fit": "符合", "unfit": "不符合", "na": "不适用"}
_SIGN_ROLES = (("编制", "preparer"), ("复核", "reviewer"), ("审核／批准", "approver"))


class ReviewRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item: str = Field(min_length=1, max_length=80, description="复核项目")
    standard: str = Field(default="", max_length=200, description="复核标准/依据")
    result: Literal["fit", "unfit", "na"] = Field(default="fit", description="复核结论")
    remark: str = Field(default="", max_length=200, description="备注/整改要求")


class InternalReviewPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: list[ReviewRow] = Field(min_length=1, max_length=100)
    title: str = Field(default="", max_length=200)
    preparer: str = Field(default="", max_length=50, description="编制人")
    reviewer: str = Field(default="", max_length=50, description="复核人")
    approver: str = Field(default="", max_length=50, description="审核/批准人")


class InternalReviewBuilder(ColumnBuilder):
    key = "internal-review"
    title = "投标文件内部复核表"
    description = "逐项复核投标文件并给出符合性结论，末尾附编制/复核/审核批准三级签署栏（三签）"
    business_types = ["supervision", "tis"]
    filename_pattern = "{project_name}_内部复核表.docx"
    payload_model = InternalReviewPayload
    default_title = "投标文件内部复核表"
    notice = "本表由软件自动生成，复核结论与签署须由质量负责人线下完成；三签齐全后方可用于投标。"
    columns = (
        Column("item", "复核项目", 3.2, "left", "text", required=True, max_length=80),
        Column("standard", "复核标准/依据", 4.0, "left", "text", max_length=200),
        Column("result", "复核结论", 2.0, "center", "select", options=RESULT_OPTIONS),
        Column("remark", "备注/整改要求", 3.4, "left", "text", max_length=200),
    )

    def add_footer_rows(self, payload, table, col_offset):
        total = len(table.columns)
        # 复核结论行
        crow = table.add_row()
        set_cell_text(crow.cells[0].merge(crow.cells[total - 1]),
                      "复核结论：□ 通过        □ 修改后通过        □ 不通过", size_pt=10)
        # 三级签署行
        for role, key in _SIGN_ROLES:
            name = getattr(payload, key, "") or ""
            srow = table.add_row()
            set_cell_text(srow.cells[0].merge(srow.cells[total - 1]),
                          f"{role}（签署）：{name or '＿＿＿＿＿＿＿＿＿＿'}　　　日期：＿＿＿＿＿＿＿＿", size_pt=10)


__all__ = ["InternalReviewBuilder", "ReviewRow", "InternalReviewPayload"]
