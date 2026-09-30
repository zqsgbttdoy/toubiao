"""附件文档生成路由。

端点：
- GET  /api/gendocs/templates                列出已注册的附件生成模板
- GET  /api/projects/{id}/gendocs            列出本项目已生成的附件文档
- POST /api/projects/{id}/gendocs            生成附件文档并存储

纪律：生成附件是纯增量的辅助产物——不调用 store.touch()，不要求 expected_version，
不触发项目版本递增或复核失效。
"""
from __future__ import annotations

import hashlib

from fastapi import APIRouter, Body, Request
from pydantic import ValidationError

from ..core import DomainError, uid
from ..exports import DOCX_MEDIA
from ..files import file_summary, safe_name, store_blob
from .registry import get_builder, list_builders

gendoc_router = APIRouter(prefix="/api", tags=["附件文档生成"])


@gendoc_router.get("/gendocs/templates")
def gendoc_templates(request: Request, business_type: str | None = None):
    """列出所有已注册的附件生成模板。"""
    return {"items": list_builders(business_type)}


@gendoc_router.get("/projects/{project_id}/gendocs")
def gendoc_list(project_id: str, request: Request):
    """列出本项目已生成的附件文档。"""
    store = request.app.state.store
    with store.transaction() as c:
        store.project(c, project_id)
        items = store.all(c, "gendoc", project_id)
    return {"items": items}


@gendoc_router.post("/projects/{project_id}/gendocs", status_code=201)
def gendoc_create(project_id: str, request: Request, body: dict = Body(...)):
    """生成附件文档并存储。不触发项目版本递增或复核失效。"""
    store = request.app.state.store
    template_key = body.get("template_key")
    payload = body.get("payload", {})
    if not template_key:
        raise DomainError("VALIDATION_ERROR", "缺少 template_key 字段", 422)
    builder = get_builder(template_key)
    try:
        validated = builder.payload_model.model_validate(payload)
    except ValidationError as exc:
        locations = [".".join(str(x) for x in e["loc"]) for e in exc.errors()[:8]]
        raise DomainError("VALIDATION_ERROR", "附件输入不符合要求：" + "、".join(locations), 422)
    with store.transaction() as c:
        project = store.project(c, project_id)
        raw = builder.build(validated, project)
        filename = builder.filename(validated, project)
        file_entity = store_blob(store, c, raw, filename, DOCX_MEDIA, purpose="generated_doc")
        item = store.save(c, "gendoc", {
            "id": uid(), "project_id": project_id,
            "template_key": template_key, "title": builder.title,
            "filename": filename,
            "file_id": file_entity["id"],
            "download_url": file_entity["download_url"],
            "sha256": file_entity["sha256"],
            "size": file_entity["size"],
        })
    return {"item": item, "file": file_summary(file_entity)}
