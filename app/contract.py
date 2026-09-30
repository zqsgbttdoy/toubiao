"""为所有API补充具体响应JSON Schema；输入由FastAPI/Pydantic直接生成。"""
from typing import Any, Generic, Literal, TypeVar
from pydantic import BaseModel, ConfigDict, Field
from fastapi.openapi.utils import get_openapi

from .schemas import (ProjectCreate, MaterialFields, TemplateFields, SnippetFields,
                      RequirementFields, SourceRef, ErrorResponse)


class Record(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    version: int
    created_at: str = Field(description="含时区ISO8601")
    updated_at: str = Field(description="含时区ISO8601")


class ProjectOut(ProjectCreate, Record):
    archived: bool
    is_demo: bool
    review_status: Literal["pending", "reviewed"]
    current_review_id: str | None
    current_draft_id: str | None
    review_invalidated_reason: str
    selected_template_ids: list[str]
    selected_material_ids: list[str]
    selected_snippet_ids: list[str]


class Locator(BaseModel):
    kind: Literal["page", "paragraph", "table", "manual"]
    page: int | None = None
    paragraph: int | None = None
    table: int | None = None
    row: int | None = None
    note: str | None = None


class Block(BaseModel):
    id: str
    text: str
    locator: Locator


class FileOut(Record):
    name: str
    sha256: str
    size: int
    media_type: str
    purpose: str
    download_url: str
    parse_status: Literal["parsed", "needs_manual_excerpt", "low_quality"] | None = None
    blocks: list[Block] = []
    warnings: list[str] = []
    page_count: int | None = None
    kind: str | None = None


class FileSummary(Record):
    """文件列表摘要；blocks 解析正文通过 GET /api/files/{file_id} 获取。"""
    name: str
    sha256: str
    size: int
    media_type: str
    purpose: str
    download_url: str
    parse_status: Literal["parsed", "needs_manual_excerpt", "low_quality"] | None = None
    page_count: int | None = None
    warnings: list[str] = []
    kind: str | None = None


class DocumentOut(Record):
    project_id: str
    title: str
    file_id: str | None
    source_family_id: str
    source_version: int
    replaces_document_id: str | None
    source_note: str
    source_type: Literal["upload", "addendum", "manual_excerpt"]
    blocks: list[Block]
    parse_status: Literal["parsed", "needs_manual_excerpt", "low_quality"]
    page_count: int | None
    warnings: list[str]


class RequirementOut(RequirementFields, Record):
    project_id: str
    original_text: str
    source_text_truncated: bool = Field(default=False, description="展示摘录是否截断；完整原文通过document_id和block_id获取")
    source_version: int
    locator: Locator
    origin: str
    detected_categories: list[str] = []


class VerificationOut(BaseModel):
    reviewer: str
    opinion: str
    status: str
    evidence_note: str
    at: str
    content_version: int
    disclaimer: str


class MaterialOut(MaterialFields, Record):
    review_status: str
    verification: VerificationOut | None
    builtin: bool
    is_demo: bool = False


class TemplateOut(TemplateFields, Record):
    review_status: str
    verification: VerificationOut | None
    builtin: bool
    copied_from: dict[str, Any] | None = None


class SnippetOut(SnippetFields, Record):
    review_status: str
    verification: VerificationOut | None
    builtin: bool
    source_version: int
    source_sha256: str
    source_blocks: list[Block]


class QuoteLineOut(BaseModel):
    name: str
    quantity: str
    unit_price: str
    unit: Literal["人月", "次", "项"]
    basis: str
    amount: str


class QuoteOut(Record):
    project_id: str
    fee_type: Literal["supervision_service", "tis_service"]
    lines: list[QuoteLineOut]
    subtotal: str
    tax_rate: str
    tax: str
    total: str
    currency: str
    rounding: str
    tax_confirmed: bool
    tax_note: str


class InputSnapshot(BaseModel):
    project: dict[str, Any]
    documents: list[DocumentOut]
    requirements: list[RequirementOut]
    quote: QuoteOut | None
    templates: list[TemplateOut]
    materials: list[MaterialOut]
    snippets: list[SnippetOut]


class SectionOut(Record):
    project_id: str
    draft_id: str
    title: str
    category: Literal["technical", "commercial", "qualification", "response", "internal"]
    order: int
    template_key: str
    template_id: str | None
    template_version: int | None
    body: str
    manually_edited: bool
    contains_quote: bool
    requirement_ids: list[str]
    references: list[SourceRef]


class DraftOut(Record):
    project_id: str
    generation: int
    previous_draft_id: str | None
    input_project_version: int
    input_snapshot: InputSnapshot
    input_hash: str
    quote_snapshot: QuoteOut | None
    generation_method: str
    reconciliations: list[dict[str, str]]
    sections: list[SectionOut] = []
    stale: bool | None = None
    is_current: bool | None = None


class DraftSummary(Record):
    """草稿列表摘要；input_snapshot 与章节正文通过 GET /drafts/{draft_id} 获取。"""
    project_id: str
    generation: int
    previous_draft_id: str | None
    input_project_version: int
    input_hash: str
    generation_method: str
    stale: bool
    is_current: bool
    section_count: int


class Issue(BaseModel):
    code: str
    message: str
    severity: Literal["blocking", "scoring", "information"]
    blocking: bool
    entity_id: str | None


class RiskOut(BaseModel):
    project_version: int
    checked_at: str
    issues: list[Issue]
    blocking_count: int
    scoring_count: int
    information_count: int
    can_finalize: bool = Field(description="仅表示没有规则阻断；仍须三类当前版本人工通过意见与明确确认")
    disclaimer: str


class DecisionOut(Record):
    project_id: str
    project_version: int
    category: Literal["technical", "commercial", "qualification"]
    reviewer: str
    opinion: str
    decision: Literal["approved", "rejected"]
    recorded_at: str
    authenticated: bool
    stale: bool | None = None


class FrozenSnapshot(BaseModel):
    project: ProjectOut
    inputs: InputSnapshot
    draft: DraftOut | None
    risk_report: RiskOut
    review_records: list[DecisionOut]
    files: list[FileOut]
    frozen_at: str
    disclaimer: str


class ReviewSnapshotOut(Record):
    project_id: str
    project_version: int
    reviewer: str
    snapshot: FrozenSnapshot
    immutable: bool


class ExportOut(Record):
    project_id: str
    project_version: int
    mode: Literal["review", "reviewed"]
    review_snapshot_id: str | None
    snapshot: FrozenSnapshot
    manifest: dict[str, Any]
    files: list[FileOut]
    immutable: bool


class ReviewSnapshotSummary(Record):
    """冻结快照摘要；完整不可变内容通过 GET /review/snapshots/{snapshot_id} 获取。"""
    project_id: str
    project_version: int
    reviewer: str
    frozen_at: str | None
    immutable: bool


class ExportSummary(Record):
    """导出摘要；完整 snapshot 通过 GET /exports/{export_id} 获取。"""
    project_id: str
    project_version: int
    mode: Literal["review", "reviewed"]
    review_snapshot_id: str | None
    manifest: dict[str, Any]
    files: list[FileOut]
    immutable: bool
    download_url: str | None = Field(default=None, description="成果ZIP下载地址")


T = TypeVar("T")


class Item(BaseModel, Generic[T]):
    item: T
    project: ProjectOut | None = None
    project_version: int | None = None


class Items(BaseModel, Generic[T]):
    items: list[T]
    project_version: int | None = None


class DocumentChange(Item[DocumentOut]):
    requirements: list[RequirementOut]


class ProjectDetail(BaseModel):
    item: ProjectOut
    documents: list[DocumentOut]
    requirements: list[RequirementOut]
    quote: QuoteOut | None
    draft: DraftOut | None
    risk_report: RiskOut
    review_records: list[DecisionOut]
    exports: list[ExportSummary]


class DraftList(Items[DraftSummary]):
    current: DraftOut | None


class ReviewOut(BaseModel):
    project_version: int
    status: str
    records: list[DecisionOut]
    risk_report: RiskOut
    current_review_id: str | None
    snapshots: list[ReviewSnapshotSummary]


class Deleted(BaseModel):
    deleted: bool
    project: ProjectOut | None = None
    message: str | None = None


class HealthOut(BaseModel):
    status: str
    version: str
    schema_version: int
    ai_mode: str
    external_ai: bool


class DashboardOut(BaseModel):
    projects: int
    active: int
    archived: int
    reviewed: int
    demo: int
    materials: int
    templates: int
    snippets: int


class SettingsOut(BaseModel):
    data_directory: str
    host: str
    port: int
    max_upload_bytes: int
    max_pdf_pages: int
    parse_timeout_seconds: float
    external_ai: bool
    cloud_ocr: bool
    telemetry: bool
    authentication: str
    schema_version: int
    privacy_notice: str
    restore_instructions: str


class HelpEntry(BaseModel):
    title: str
    text: str


class DemoOut(Items[ProjectOut]):
    already_loaded: bool


class BackupOut(Record):
    name: str
    size: int
    sha256: str
    download_url: str
    manifest: dict[str, Any]


class EventOut(BaseModel):
    id: int
    at: str
    action: str
    entity_id: str
    project_id: str | None


class AIConfigOut(Record):
    """AI服务配置；api_key仅回显掩码，绝不返回明文。"""
    enabled: bool
    provider: Literal["null", "ollama", "openai_compat"]
    base_url: str
    model: str
    embedding_model: str
    api_key_masked: str = Field(description="形如****abcd；空字符串表示未设置密钥")
    is_cloud: bool
    redaction_level: Literal["standard", "strict"]
    default_scope: list[str]
    max_concurrent: int
    daily_token_budget: int
    timeout_seconds: float
    external_ai: bool = Field(description="enabled且provider非null时为true")


class AITestOut(BaseModel):
    reachable: bool
    reason: str = ""
    provider: str
    model: str
    models: list[str] = []
    latency_ms: int = 0
    base_url: str = ""


class AIPreviewOut(BaseModel):
    preview_id: str
    feature: str
    project_id: str
    project_version: int
    provider: str
    model: str
    redaction_level: Literal["standard", "strict"]
    redaction_summary: dict[str, int] = Field(description="各类敏感信息命中计数")
    masked_tokens: int
    estimated_tokens: int
    scope_applied: list[str]
    redacted_text: str = Field(description="脱敏后待发送正文的回显（可能截断）")
    warnings: list[str] = []
    expires_in_seconds: int
    disclaimer: str


class AIDegradation(BaseModel):
    to: str
    code: str
    message: str


class AIResultOut(BaseModel):
    status: Literal["success", "fallback"]
    feature: str
    provider: str
    model: str
    text: str
    origin: Literal["ai_suggestion", "rule_engine"]
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str
    degradation: AIDegradation | None = None
    disclaimer: str
    call_id: int | None = Field(default=None, description="对应审计日志ID")


class AICallSummaryOut(BaseModel):
    """审计列表摘要；不含prompt_preview/response_preview重字段。"""
    id: int
    at: str
    project_id: str | None
    entity_kind: str | None
    entity_id: str | None
    phase: int
    feature: str
    provider: str
    model: str | None
    endpoint_masked: str | None
    prompt_tokens: int
    response_tokens: int
    user_confirmed: bool
    latency_ms: int
    status: str
    error_code: str | None
    fallback_used: bool
    origin_mark: str | None


class AICallDetailOut(AICallSummaryOut):
    prompt_hash: str | None
    prompt_preview: str | None
    response_hash: str | None
    response_preview: str | None
    redaction_summary: dict[str, Any] | None
    scope_applied: list[str] | None
    confirmation_at: str | None


class AICallList(Items[AICallSummaryOut]):
    total: int


def attach_response_contract(app):
    models = {
        "project_list": Items[ProjectOut], "project_create": Item[ProjectOut], "project_detail": ProjectDetail,
        "project_update": Item[ProjectOut], "project_archive": Item[ProjectOut], "project_delete": Deleted,
        "project_selection": Item[ProjectOut], "documents": Items[DocumentOut], "document_upload": DocumentChange,
        "manual_excerpt": DocumentChange, "document_detail": Item[DocumentOut], "requirements": Items[RequirementOut],
        "requirement_create": Item[RequirementOut], "requirement_update": Item[RequirementOut], "requirement_delete": Deleted,
        "quote_get": Item[QuoteOut | None], "quote_save": Item[QuoteOut], "drafts_get": DraftList,
        "draft_get": Item[DraftOut], "draft_generate": Item[DraftOut], "draft_reconcile": Item[DraftOut],
        "section_edit": Item[SectionOut], "section_insert": Item[SectionOut], "review_get": ReviewOut,
        "review_snapshot_detail": Item[ReviewSnapshotOut],
        "review_check": Item[RiskOut], "review_decision": Item[DecisionOut], "review_finalize": Item[ReviewSnapshotOut],
        "export_list": Items[ExportSummary], "export_create": Item[ExportSummary], "export_detail": Item[ExportOut],
        "backup_create": Item[BackupOut], "health": HealthOut, "dashboard": DashboardOut,
        "get_settings": SettingsOut, "help_content": Items[HelpEntry], "demo": DemoOut,
        "list_files": Items[FileSummary], "upload_file": Item[FileOut], "file_metadata": Item[FileOut],
        "project_events": Items[EventOut], "template_copy": Item[TemplateOut],
        "ai_config_get": Item[AIConfigOut], "ai_config_update": Item[AIConfigOut],
        "ai_test": Item[AITestOut], "ai_preview": Item[AIPreviewOut], "ai_invoke": Item[AIResultOut],
        "ai_calls": AICallList, "ai_call_detail": Item[AICallDetailOut],
    }
    for prefix, plural, model in [("material", "materials", MaterialOut), ("template", "templates", TemplateOut), ("snippet", "snippets", SnippetOut)]:
        models[plural] = Items[model]
        for suffix in ("create", "detail", "update", "verify"):
            models[prefix + "_" + suffix] = Item[model]
        models[prefix + "_history"] = Items[model]
        models[prefix + "_delete"] = Deleted

    def openapi():
        if app.openapi_schema:
            return app.openapi_schema
        result = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)
        components = result.setdefault("components", {}).setdefault("schemas", {})
        for route in app.routes:
            if not hasattr(route, "methods") or route.path not in result["paths"]:
                continue
            model = models.get(route.name)
            for method in route.methods:
                operation = result["paths"][route.path].get(method.lower())
                if not operation:
                    continue
                status = str(getattr(route, "status_code", None) or 200)
                if model:
                    schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
                    components.update(schema.pop("$defs", {}))
                    operation["responses"][status] = {"description": "操作成功；版本变化后应使用响应中的新版本", "content": {"application/json": {"schema": schema}}}
                elif route.name in ("file_download", "backup_download"):
                    operation["responses"][status] = {"description": "受控原始字节下载；X-Content-SHA256为文件哈希", "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}}
                if method not in ("GET", "HEAD"):
                    operation.setdefault("parameters", []).append({"name": "Origin", "in": "header", "required": True,
                        "description": "必须与Host同源，例如http://127.0.0.1:8000；浏览器原生同源请求自动携带", "schema": {"type": "string"}})
        components["ErrorResponse"] = ErrorResponse.model_json_schema()
        app.openapi_schema = result
        return result
    app.openapi = openapi
