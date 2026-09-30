"""章节类附件生成器（P0 批次 1E）：监理大纲14章 / TIS风险减量服务方案11章。

复用 section_kit 引擎，正文的唯一数据源是 templates/builtin.json 对应模板的 sections，
本文件只声明「用哪个框架、适用哪类业务、文档标题」，不重复维护章节文字。
新增章节类附件（如区域专用大纲）只需再加一个 SectionBuilder 子类并注册到 registry。
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .section_kit import SectionBuilder


class SectionPayload(BaseModel):
    """章节类附件输入契约：可覆盖文档标题、开关目录与编制指引。"""
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="", max_length=200, description="文档标题（留空用标准标题）")
    include_toc: bool = Field(default=True, description="生成目录页")
    include_guidance: bool = Field(default=True, description="保留【本章要点】【评分对应】编制指引")


class SupervisionOutlineBuilder(SectionBuilder):
    key = "supervision-outline"
    title = "监理大纲（技术建议书14章）"
    description = "按标准 14 章框架生成监理技术建议书，含目录、逐章要点与评分对应指引（仅监理类）"
    business_types = ["supervision"]
    filename_pattern = "{project_name}_监理大纲.docx"
    payload_model = SectionPayload
    template_id = "builtin-supervision-outline"
    doc_title = "监理大纲（技术建议书）"


class TisPlanBuilder(SectionBuilder):
    key = "tis-plan"
    title = "TIS 风险减量服务方案（11章）"
    description = "按标准 11 章框架生成 TIS 风险减量服务方案，含目录与逐章要点指引（仅 TIS 类）"
    business_types = ["tis"]
    filename_pattern = "{project_name}_TIS服务方案.docx"
    payload_model = SectionPayload
    template_id = "builtin-tis-plan"
    doc_title = "TIS 风险减量服务方案"


__all__ = ["SectionPayload", "SupervisionOutlineBuilder", "TisPlanBuilder"]
