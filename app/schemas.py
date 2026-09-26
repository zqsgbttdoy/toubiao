"""公开API输入契约。未知字段一律拒绝，避免客户端自行设置审核结论。"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)]
Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
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


class ErrorResponse(BaseModel):
    code: str
    message: str
