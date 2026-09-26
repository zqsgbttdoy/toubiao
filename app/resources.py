"""可版本化企业资料、参考模板与人工选择的历史素材。"""
import json
from fastapi import APIRouter, Request

from .core import ROOT, DomainError, now, uid
from .schemas import (MaterialCreate, MaterialUpdate, TemplateCreate, TemplateUpdate,
                      SnippetCreate, SnippetUpdate, Verification, CopyTemplate, Version)

router = APIRouter(prefix="/api", tags=["共享资源"])


def seed_templates(store):
    with store.transaction() as c:
        for entry in json.loads((ROOT / "templates" / "builtin.json").read_text(encoding="utf-8")):
            if not store.get(c, "template", entry["id"], False):
                store.save(c, "template", {**entry, "builtin": True, "review_status": "pending", "verification": None})


def listing(request, kind, q="", business_type=None, tag=None):
    store = request.app.state.store
    with store.transaction() as c:
        items = store.all(c, kind)
    items = [x for x in items if not business_type or business_type in x["business_types"]]
    items = [x for x in items if not tag or tag in x.get("tags", [])]
    if q:
        items = [x for x in items if q.casefold() in json.dumps(x, ensure_ascii=False).casefold()]
    items.sort(key=lambda x: x.get("review_status") != "approved")
    return {"items": items}


def detail(request, kind, entity_id):
    store = request.app.state.store
    with store.transaction() as c:
        return {"item": store.get(c, kind, entity_id)}


def history(request, kind, entity_id):
    store = request.app.state.store
    with store.transaction() as c:
        store.get(c, kind, entity_id)
        return {"items": store.history(c, kind, entity_id)}


def validate_resource(store, c, kind, data):
    if kind == "material":
        for file_id in data["file_ids"]:
            store.get(c, "file", file_id)
    if kind == "snippet":
        source = store.get(c, "file", data["source_file_id"])
        chosen = [b for b in source.get("blocks", []) if b["id"] in data["source_block_ids"]]
        if len({b["id"] for b in chosen}) != len(set(data["source_block_ids"])):
            raise DomainError("SOURCE_BLOCK_MISSING", "所选内容块不属于该历史来源", 422)
        data["source_version"] = source["version"]
        data["source_sha256"] = source["sha256"]
        data["source_blocks"] = chosen


def create_resource(request, kind, body):
    store = request.app.state.store
    data = body.model_dump(mode="json")
    with store.transaction() as c:
        validate_resource(store, c, kind, data)
        item = store.save(c, kind, {"id": uid(), **data, "review_status": "pending", "verification": None, "builtin": False})
        return {"item": item}


def update_resource(request, kind, entity_id, body):
    store = request.app.state.store
    data = body.model_dump(mode="json", exclude={"expected_version"})
    with store.transaction() as c:
        old = store.get(c, kind, entity_id)
        store.expect(old, body.expected_version)
        if old.get("builtin"):
            raise DomainError("BUILTIN_READONLY", "内置模板保留来源，请先复制后编辑", 409)
        validate_resource(store, c, kind, data)
        item = store.save(c, kind, {**old, **data, "review_status": "pending", "verification": None})
        store.invalidate_resource(c, kind, entity_id)
        return {"item": item}


def verify_resource(request, kind, entity_id, body):
    store = request.app.state.store
    with store.transaction() as c:
        item = store.get(c, kind, entity_id)
        store.expect(item, body.expected_version)
        item["review_status"] = body.status
        item["verification"] = {"reviewer": body.reviewer, "opinion": body.opinion,
            "status": body.status, "evidence_note": body.evidence_note, "at": now(),
            "content_version": item["version"] + 1,
            "disclaimer": "仅为人工核验记录，审核通过不表示软件自动认定资料真实有效。"}
        item = store.save(c, kind, item, "verify")
        store.invalidate_resource(c, kind, entity_id)
        return {"item": item}


def delete_resource(request, kind, entity_id, body):
    store = request.app.state.store
    with store.transaction() as c:
        item = store.get(c, kind, entity_id)
        store.expect(item, body.expected_version)
        if item.get("builtin"):
            raise DomainError("BUILTIN_READONLY", "内置参考模板不可删除", 409)
        key = {"material": "selected_material_ids", "template": "selected_template_ids", "snippet": "selected_snippet_ids"}[kind]
        if any(entity_id in p.get(key, []) for p in store.all(c, "project")):
            raise DomainError("RESOURCE_IN_USE", "资料仍被项目选用，请先解除关联；历史快照将保留", 409)
        store.delete(c, kind, entity_id)
        return {"deleted": True}


@router.get("/materials")
def materials(request: Request, q: str = "", business_type: str | None = None, tag: str | None = None):
    return listing(request, "material", q, business_type, tag)


@router.post("/materials", status_code=201)
def material_create(body: MaterialCreate, request: Request):
    return create_resource(request, "material", body)


@router.get("/materials/{entity_id}")
def material_detail(entity_id: str, request: Request):
    return detail(request, "material", entity_id)


@router.put("/materials/{entity_id}")
def material_update(entity_id: str, body: MaterialUpdate, request: Request):
    return update_resource(request, "material", entity_id, body)


@router.delete("/materials/{entity_id}")
def material_delete(entity_id: str, body: Version, request: Request):
    return delete_resource(request, "material", entity_id, body)


@router.get("/materials/{entity_id}/versions")
def material_history(entity_id: str, request: Request):
    return history(request, "material", entity_id)


@router.post("/materials/{entity_id}/verify")
def material_verify(entity_id: str, body: Verification, request: Request):
    return verify_resource(request, "material", entity_id, body)


@router.get("/templates")
def templates(request: Request, q: str = "", business_type: str | None = None, tag: str | None = None):
    return listing(request, "template", q, business_type, tag)


@router.post("/templates", status_code=201)
def template_create(body: TemplateCreate, request: Request):
    return create_resource(request, "template", body)


@router.get("/templates/{entity_id}")
def template_detail(entity_id: str, request: Request):
    return detail(request, "template", entity_id)


@router.put("/templates/{entity_id}")
def template_update(entity_id: str, body: TemplateUpdate, request: Request):
    return update_resource(request, "template", entity_id, body)


@router.delete("/templates/{entity_id}")
def template_delete(entity_id: str, body: Version, request: Request):
    return delete_resource(request, "template", entity_id, body)


@router.post("/templates/{entity_id}/copy", status_code=201)
def template_copy(entity_id: str, body: CopyTemplate, request: Request):
    store = request.app.state.store
    with store.transaction() as c:
        old = store.get(c, "template", entity_id)
        store.expect(old, body.expected_version)
        data = {k: v for k, v in old.items() if k not in ("id", "version", "created_at", "updated_at")}
        data.update(name=body.name, builtin=False, review_status="pending", verification=None,
                    copied_from={"id": old["id"], "version": old["version"], "source": old["source"]})
        return {"item": store.save(c, "template", {"id": uid(), **data})}


@router.get("/templates/{entity_id}/versions")
def template_history(entity_id: str, request: Request):
    return history(request, "template", entity_id)


@router.post("/templates/{entity_id}/verify")
def template_verify(entity_id: str, body: Verification, request: Request):
    return verify_resource(request, "template", entity_id, body)


@router.get("/snippets")
def snippets(request: Request, q: str = "", business_type: str | None = None, tag: str | None = None):
    return listing(request, "snippet", q, business_type, tag)


@router.post("/snippets", status_code=201)
def snippet_create(body: SnippetCreate, request: Request):
    return create_resource(request, "snippet", body)


@router.get("/snippets/{entity_id}")
def snippet_detail(entity_id: str, request: Request):
    return detail(request, "snippet", entity_id)


@router.put("/snippets/{entity_id}")
def snippet_update(entity_id: str, body: SnippetUpdate, request: Request):
    return update_resource(request, "snippet", entity_id, body)


@router.delete("/snippets/{entity_id}")
def snippet_delete(entity_id: str, body: Version, request: Request):
    return delete_resource(request, "snippet", entity_id, body)


@router.get("/snippets/{entity_id}/versions")
def snippet_history(entity_id: str, request: Request):
    return history(request, "snippet", entity_id)


@router.post("/snippets/{entity_id}/verify")
def snippet_verify(entity_id: str, body: Verification, request: Request):
    return verify_resource(request, "snippet", entity_id, body)
