"""公开API输入契约。未知字段一律拒绝，避免客户端自行设置审核结论。"""
from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Literal
from urllib.parse import urlparse
from pydantic import (AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field,
                      StringConstraints, model_validator)

# 允许换行、回车与制表符；其余C0控制字符和DEL一律拒绝，
# 避免NUL写入SQLite造成静默截断、input_hash与正文不一致。
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def reject_control_chars(value: str) -> str:
    if _CONTROL_RE.search(value):
        raise ValueError("不得包含控制字符（如NUL），请删除后重新提交")
    return value


Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000), AfterValidator(reject_control_chars)]
Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200), AfterValidator(reject_control_chars)]
Id = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_-]{1,100}$")]
Business = Literal["supervision", "tis"]
Category = Literal["qualification", "mandatory", "scoring", "delivery", "pricing"]
SectionCategory = Literal["technical", "commercial", "qualification", "response", "internal"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Version(Input):
    expected_version: int = Field(ge=1, description="项目操作为当前项目version，共享资源操作为该资源version")


class EntityVersion(Version):
    entity_version: int = Field(ge=1, description="被编辑的需求、章节或报价当前version")


class Fact(Input):
    value: Short
    confirmed: bool = False
    source: str = Field(default="人工录入", max_length=500)


class ProjectCreate(Input):
    name: Short
    business_type: Business
    region: str = Field(default="", max_length=200)
    client: str = Field(default="", max_length=200)
    scope: str = Field(default="", max_length=20000)
    deadline: AwareDatetime | None = None
    facts: dict[str, Fact] = Field(default_factory=dict, max_length=100)


class ProjectUpdate(ProjectCreate, Version):
    pass


class Archive(Version):
    archived: bool


class Selection(Version):
    template_ids: list[Id] = Field(default_factory=list, max_length=50)
    material_ids: list[Id] = Field(default_factory=list, max_length=100)
    snippet_ids: list[Id] = Field(default_factory=list, max_length=100)


class Excerpt(Version):
    title: Short
    text: Text
    source_note: Short
    replaces_document_id: Id | None = None


class RequirementFields(Input):
    text: Text
    category: Category
    mandatory: bool = False
    confirmed: bool = False
    response_status: Literal["pending", "responded", "gap", "not_applicable"] = "pending"
    response_note: str = Field(default="", max_length=10000)
    section_id: Id | None = None
    proof_material_ids: list[Id] = Field(default_factory=list, max_length=100)
    document_id: Id | None = None
    block_id: Id | None = None
    source_note: str = Field(default="人工录入", max_length=500)

    @model_validator(mode="after")
    def source_pair(self):
        if bool(self.document_id) != bool(self.block_id):
            raise ValueError("document_id和block_id必须同时提供")
        return self


class RequirementCreate(RequirementFields, Version):
    pass


class RequirementUpdate(RequirementFields, EntityVersion):
    pass


class MaterialFields(Input):
    name: Short
    kind: Literal["qualification", "personnel", "experience"]
    business_types: list[Business] = Field(min_length=1, max_length=2)
    description: str = Field(default="", max_length=20000)
    valid_from: date | None = None
    valid_until: date | None = None
    validity_note: str = Field(default="", max_length=500, description="无到期日时说明长期有效或业绩性质")
    scope: str = Field(default="", max_length=2000)
    file_ids: list[Id] = Field(default_factory=list, max_length=50)
    tags: list[Short] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def dates(self):
        if self.valid_from and self.valid_until and self.valid_from > self.valid_until:
            raise ValueError("有效期起始日不能晚于截止日")
        return self


class MaterialCreate(MaterialFields):
    pass


class MaterialUpdate(MaterialFields, Version):
    pass


class Verification(Version):
    reviewer: Short
    opinion: Text
    status: Literal["approved", "rejected"]
    evidence_note: Short


class TemplateSection(Input):
    key: Id
    title: Short
    category: SectionCategory
    body: Text


class TemplateFields(Input):
    name: Short
    business_types: list[Business] = Field(min_length=1, max_length=2)
    sections: list[TemplateSection] = Field(min_length=1, max_length=30)
    source: Short
    tags: list[Short] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def unique_keys(self):
        if len({s.key for s in self.sections}) != len(self.sections):
            raise ValueError("模板章节key不可重复")
        return self


class TemplateCreate(TemplateFields):
    pass


class TemplateUpdate(TemplateFields, Version):
    pass


class CopyTemplate(Version):
    name: Short


class SnippetFields(Input):
    title: Short
    content: Text
    business_types: list[Business] = Field(min_length=1, max_length=2)
    tags: list[Short] = Field(default_factory=list, max_length=30)
    source_file_id: Id
    source_block_ids: list[Id] = Field(min_length=1, max_length=100)


class SnippetCreate(SnippetFields):
    pass


class SnippetUpdate(SnippetFields, Version):
    pass


class QuoteLine(Input):
    name: Short
    quantity: str = Field(max_length=30, description="非负十进制字符串，最多3位小数")
    unit_price: str = Field(max_length=30, description="非负十进制字符串，最多2位小数")
    unit: Literal["人月", "次", "项"]
    basis: Short


class QuoteSave(Version):
    entity_version: int = Field(ge=0, description="首次报价为0，后续为报价version")
    fee_type: Literal["supervision_service", "tis_service"]
    lines: list[QuoteLine] = Field(min_length=1, max_length=200)
    tax_rate: str = Field(max_length=20, description="0至1之间的小数，如0.06；不是百分数6")
    tax_confirmed: bool
    tax_note: Short


class Generate(Version):
    confirm_regenerate: bool = False


class SourceRef(Input):
    kind: Literal["material", "snippet", "template", "document"]
    id: Id
    version: int = Field(ge=1)


class SectionEdit(EntityVersion):
    body: str = Field(max_length=100000)
    requirement_ids: list[Id] = Field(default_factory=list, max_length=300)
    references: list[SourceRef] = Field(default_factory=list, max_length=200)


class InsertSnippet(EntityVersion):
    snippet_id: Id
    snippet_version: int = Field(ge=1)


class ReconcileDraft(Version):
    reviewer: Short
    note: Text
    confirmed: bool


class ReviewDecision(Version):
    entity_version: int = Field(ge=0, description="首次该类别审核为0，否则为当前记录version")
    category: Literal["technical", "commercial", "qualification"]
    reviewer: Short
    opinion: Text
    decision: Literal["approved", "rejected"]


class FinalizeReview(Version):
    reviewer: Short
    confirmation: bool


class ExportRequest(Version):
    mode: Literal["review", "reviewed"] = "review"


class DemoLoad(Input):
    confirmation: bool


AIProviderName = Literal["null", "ollama", "openai_compat"]
# Phase 1仅开放招标文件智能摘要；分类/生成在后续阶段解锁。
AIFeature = Literal["summarize"]

# 非云端部署时base_url仅允许本机回环，防止内网横向探测。
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}


class AIConfigUpdate(Version):
    enabled: bool = False
    provider: AIProviderName = "null"
    base_url: str = Field(default="", max_length=500, description="OpenAI兼容端点，Ollama需含/v1；空表示不修改")
    model: str = Field(default="", max_length=200)
    embedding_model: str = Field(default="", max_length=200)
    api_key: str | None = Field(default=None, max_length=500, description="含*视为掩码回显，保留原密钥不变")
    is_cloud: bool = False
    redaction_level: Literal["standard", "strict"] = "standard"
    default_scope: list[str] = Field(default_factory=lambda: ["documents"], max_length=10)
    max_concurrent: int = Field(default=1, ge=1, le=4)
    daily_token_budget: int = Field(default=200000, ge=0, le=100000000)
    timeout_seconds: float = Field(default=120.0, ge=5.0, le=600.0)

    @model_validator(mode="after")
    def coherence(self):
        if self.is_cloud and self.redaction_level != "strict":
            raise ValueError("云端模型必须使用strict脱敏等级")
        url = self.base_url.strip()
        if url:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                raise ValueError("base_url必须是合法的http或https地址")
            if not self.is_cloud and parsed.hostname.lower() not in _LOCAL_HOSTS:
                raise ValueError("未勾选云端时，base_url仅允许127.0.0.1、localhost或::1")
        if self.enabled:
            if self.provider == "null":
                raise ValueError("启用AI时必须选择ollama或openai_compat提供方")
            if not url or not self.model.strip():
                raise ValueError("启用AI时必须填写base_url与model")
        return self


class AIScope(Input):
    include_documents: bool = True
    document_ids: list[Id] = Field(default_factory=list, max_length=50,
                                   description="限定来源版本；空表示项目全部当前来源")
    include_facts: bool = Field(default=False, description="Phase 1默认仅发送招标文件正文")


class AIPreviewRequest(Input):
    feature: AIFeature
    project_id: Id
    scope: AIScope = Field(default_factory=AIScope)


class AIInvokeRequest(Input):
    preview_id: str = Field(min_length=8, max_length=64)
    user_confirmed: bool


class ErrorResponse(BaseModel):
    code: str
    message: str
