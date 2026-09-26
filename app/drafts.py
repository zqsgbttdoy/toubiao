"""规则模板组装、输入快照、章节修订与来源版本追溯。"""
import hashlib
import re
from fastapi import APIRouter, Request

from .core import DomainError, dumps, now, uid
from .pricing import quote_text
from .schemas import Generate, SectionEdit, InsertSnippet, ReconcileDraft

router = APIRouter(prefix="/api/projects", tags=["章节草稿"])


def input_snapshot(store, c, p):
    keys = ("name", "business_type", "region", "client", "scope", "deadline", "facts",
            "selected_template_ids", "selected_material_ids", "selected_snippet_ids")
    snapshot = {"project": {k: p.get(k) for k in keys},
        "documents": store.all(c, "document", p["id"]),
        "requirements": store.all(c, "requirement", p["id"]),
        "quote": store.get(c, "quote", p["id"], False)}
    for kind in ("template", "material", "snippet"):
        snapshot[kind + "s"] = [store.get(c, kind, entity_id) for entity_id in p.get(f"selected_{kind}_ids", [])]
    return snapshot


def fingerprint(snapshot):
    return hashlib.sha256(dumps(snapshot).encode("utf-8")).hexdigest()


def current_sections(store, c, p, draft_id=None):
    draft_id = draft_id or p.get("current_draft_id")
    return sorted([s for s in store.all(c, "section", p["id"]) if s["draft_id"] == draft_id], key=lambda s: s["order"])


def draft_detail(store, c, p, draft_id=None):
    draft_id = draft_id or p.get("current_draft_id")
    if not draft_id:
        return None
    draft = store.child(c, "draft", draft_id, p["id"])
    return {**draft, "sections": current_sections(store, c, p, draft_id),
            "stale": draft["input_hash"] != fingerprint(input_snapshot(store, c, p)),
            "is_current": draft_id == p.get("current_draft_id")}


def reference(resource, kind):
    return {"kind": kind, "id": resource["id"], "version": resource["version"]}


def render(body, snapshot):
    p = snapshot["project"]
    facts = p["facts"]
    material_lines = []
    for m in snapshot["materials"]:
        state = "已人工核验记录" if m["review_status"] == "approved" else "待核验，不代表真实有效"
        material_lines.append(f"{m['name']}（{m['kind']}，版本{m['version']}，{state}）；范围：{m.get('scope') or '【待填：适用范围】'}；说明：{m.get('description', '')}")
    confirmed = [r for r in snapshot["requirements"] if r["confirmed"]]
    values = {
        "facts": "\n".join(f"{k}：{v['value']}（依据：{v['source']}）" for k, v in facts.items() if v["confirmed"]) or "【待填：已确认项目事实】",
        "materials": "\n".join(material_lines) or "【待填：选用企业资质、人员及业绩材料】",
        "quote": quote_text(snapshot["quote"]),
        "requirements": "\n".join(f"[{r['id'][:8]}] {r['text']}；响应：{r['response_status']}；说明：{r['response_note']}" for r in confirmed) or "【待填：人工确认需求及响应】",
    }
    def replace(match):
        key = match.group(1).strip()
        if key.startswith("project."):
            name = key[8:]
            return str(p.get(name) or f"【待填：{name}】")
        if key.startswith("fact."):
            fact = facts.get(key[5:])
            return fact["value"] if fact and fact["confirmed"] else f"【待填：{key[5:]}，需人工确认】"
        return values.get(key, f"【待填：{key}】")
    return re.sub(r"\{\{\s*([^{}]+?)\s*\}\}", replace, body)


def check_reference(store, c, p, ref):
    item = store.get(c, ref["kind"], ref["id"])
    store.expect(item, ref["version"])
    if ref["kind"] == "document":
        if item["project_id"] != p["id"]:
            raise DomainError("SOURCE_SCOPE", "不能引用其他项目招标来源", 422)
    elif ref["id"] not in p.get(f"selected_{ref['kind']}_ids", []):
        raise DomainError("SOURCE_NOT_SELECTED", "请先在项目选用资料中选择此来源", 422)
    return item


@router.get("/{project_id}/drafts")
def drafts_get(project_id: str, request: Request):
    store = request.app.state.store
    with store.transaction() as c:
        p = store.project(c, project_id)
        return {"items": store.all(c, "draft", project_id), "current": draft_detail(store, c, p), "project_version": p["version"]}


@router.get("/{project_id}/drafts/{draft_id}")
def draft_get(project_id: str, draft_id: str, request: Request):
    store = request.app.state.store
    with store.transaction() as c:
        p = store.project(c, project_id)
        return {"item": draft_detail(store, c, p, draft_id), "project_version": p["version"]}


@router.post("/{project_id}/drafts/generate", status_code=201)
def draft_generate(project_id: str, body: Generate, request: Request):
    store = request.app.state.store
    with store.transaction() as c:
        p = store.project(c, project_id, body.expected_version, True)
        if p.get("current_draft_id") and not body.confirm_regenerate:
            raise DomainError("REGENERATE_CONFIRMATION_REQUIRED", "再次生成会新建版本并保留旧稿，请明确确认", 409)
        snapshot = input_snapshot(store, c, p)
        if not snapshot["templates"]:
            raise DomainError("TEMPLATE_REQUIRED", "请先选择至少一个适用模板", 422)
        for resource in snapshot["templates"] + snapshot["materials"] + snapshot["snippets"]:
            if p["business_type"] not in resource["business_types"]:
                raise DomainError("BUSINESS_SCOPE_MISMATCH", "所选模板或资料业务类型不适用", 422)
        draft_id = uid()
        old_sections = current_sections(store, c, p)
        remap = {}
        sections = []
        for template in snapshot["templates"]:
            for part in template["sections"]:
                section_id = uid()
                key = template["id"] + ":" + part["key"]
                previous = next((s for s in old_sections if s["template_key"] == key), None)
                if previous:
                    remap[previous["id"]] = section_id
                sections.append({"id": section_id, "project_id": project_id, "draft_id": draft_id,
                    "title": part["title"], "category": part["category"], "order": len(sections),
                    "template_key": key, "template_id": template["id"], "template_version": template["version"],
                    "body": render(part["body"], snapshot), "manually_edited": False,
                    "contains_quote": bool(re.search(r"\{\{\s*quote\s*\}\}", part["body"])),
                    "requirement_ids": [], "references": [reference(template, "template")] +
                    [reference(m, "material") for m in snapshot["materials"]]})
        for snippet in snapshot["snippets"]:
            section_id = uid()
            key = "snippet:" + snippet["id"]
            previous = next((s for s in old_sections if s["template_key"] == key), None)
            if previous:
                remap[previous["id"]] = section_id
            sections.append({"id": section_id, "project_id": project_id, "draft_id": draft_id,
                "title": "选用历史素材：" + snippet["title"], "category": "technical", "order": len(sections),
                "template_key": key, "template_id": None, "template_version": None,
                "body": snippet["content"], "manually_edited": False, "contains_quote": False,
                "requirement_ids": [], "references": [reference(snippet, "snippet")]})
        for requirement in snapshot["requirements"]:
            if requirement.get("section_id") in remap:
                requirement["section_id"] = remap[requirement["section_id"]]
                store.save(c, "requirement", requirement, "remap_regenerated_section")
        snapshot = input_snapshot(store, c, p)
        for section in sections:
            section["requirement_ids"] = [r["id"] for r in snapshot["requirements"] if r.get("section_id") == section["id"]]
            store.save(c, "section", section)
        draft = store.save(c, "draft", {"id": draft_id, "project_id": project_id,
            "generation": len(store.all(c, "draft", project_id)) + 1, "previous_draft_id": p.get("current_draft_id"),
            "input_project_version": p["version"] + 1, "input_snapshot": snapshot, "input_hash": fingerprint(snapshot),
            "quote_snapshot": snapshot["quote"], "generation_method": "本地规则与参考模板组装，外部AI未接入",
            "reconciliations": []})
        p["current_draft_id"] = draft_id
        p = store.touch(c, p, "已生成新草稿，需要内部复核")
        return {"item": draft_detail(store, c, p), "project": p}


@router.put("/{project_id}/drafts/{draft_id}/sections/{section_id}")
def section_edit(project_id: str, draft_id: str, section_id: str, body: SectionEdit, request: Request):
    store = request.app.state.store
    with store.transaction() as c:
        p = store.project(c, project_id, body.expected_version, True)
        if p.get("current_draft_id") != draft_id:
            raise DomainError("OLD_DRAFT_READONLY", "旧稿只读，请编辑当前草稿", 409)
        section = store.child(c, "section", section_id, project_id)
        if section["draft_id"] != draft_id:
            raise DomainError("NOT_FOUND", "章节不属于当前草稿", 404)
        store.expect(section, body.entity_version)
        draft = store.get(c, "draft", draft_id)
        if section["contains_quote"] and quote_text(draft["quote_snapshot"]) not in body.body:
            raise DomainError("QUOTE_TEXT_LOCKED", "报价正文必须保留完整权威报价块；请到报价页修改并重新生成", 422)
        for requirement_id in body.requirement_ids:
            store.child(c, "requirement", requirement_id, project_id)
        refs = [r.model_dump() for r in body.references]
        for ref in refs:
            check_reference(store, c, p, ref)
        if section.get("template_id"):
            provenance = {"kind": "template", "id": section["template_id"], "version": section["template_version"]}
            if provenance not in refs:
                refs.append(provenance)
        section.update(body=body.body, references=refs, requirement_ids=body.requirement_ids, manually_edited=True)
        item = store.save(c, "section", section)
        from .projects import sync_requirement_sections
        for requirement in store.all(c, "requirement", project_id):
            target = section_id if requirement["id"] in body.requirement_ids else requirement.get("section_id")
            if requirement["id"] not in body.requirement_ids and target == section_id:
                target = None
            if target != requirement.get("section_id"):
                requirement["section_id"] = target
                store.save(c, "requirement", requirement, "section_editor_link")
                sync_requirement_sections(store, c, p, requirement["id"], target)
        store.save(c, "draft", draft, "section_edited")
        return {"item": item, "project": store.touch(c, p, "章节已人工编辑")}


@router.post("/{project_id}/drafts/{draft_id}/sections/{section_id}/insert-snippet")
def section_insert(project_id: str, draft_id: str, section_id: str, body: InsertSnippet, request: Request):
    store = request.app.state.store
    with store.transaction() as c:
        p = store.project(c, project_id, body.expected_version, True)
        if p.get("current_draft_id") != draft_id:
            raise DomainError("OLD_DRAFT_READONLY", "旧稿只读", 409)
        section = store.child(c, "section", section_id, project_id)
        if section["draft_id"] != draft_id:
            raise DomainError("NOT_FOUND", "章节不属于当前草稿", 404)
        store.expect(section, body.entity_version)
        snippet = store.get(c, "snippet", body.snippet_id)
        store.expect(snippet, body.snippet_version)
        if p["business_type"] not in snippet["business_types"]:
            raise DomainError("BUSINESS_SCOPE_MISMATCH", "素材不适用于当前业务类型", 422)
        if snippet["id"] not in p["selected_snippet_ids"]:
            p["selected_snippet_ids"].append(snippet["id"])
        section["body"] += "\n\n" + snippet["content"]
        section["references"].append(reference(snippet, "snippet"))
        section["manually_edited"] = True
        item = store.save(c, "section", section)
        store.save(c, "draft", store.get(c, "draft", draft_id), "snippet_inserted")
        return {"item": item, "project": store.touch(c, p, "插入历史素材，请核对后同步草稿输入快照")}


@router.post("/{project_id}/drafts/{draft_id}/reconcile")
def draft_reconcile(project_id: str, draft_id: str, body: ReconcileDraft, request: Request):
    store = request.app.state.store
    with store.transaction() as c:
        p = store.project(c, project_id, body.expected_version, True)
        if not body.confirmed or p.get("current_draft_id") != draft_id:
            raise DomainError("CONFIRMATION_REQUIRED", "仅可明确确认当前草稿已逐章核对", 422)
        draft = store.child(c, "draft", draft_id, project_id)
        snapshot = input_snapshot(store, c, p)
        if draft["quote_snapshot"] != snapshot["quote"]:
            raise DomainError("QUOTE_REGEN_REQUIRED", "报价发生变化，必须重新生成以保持正文和报价快照一致", 409)
        for section in current_sections(store, c, p):
            for ref in section["references"]:
                check_reference(store, c, p, ref)
        draft["input_snapshot"] = snapshot
        draft["input_hash"] = fingerprint(snapshot)
        draft["input_project_version"] = p["version"] + 1
        draft["reconciliations"].append({"reviewer": body.reviewer, "note": body.note, "at": now()})
        store.save(c, "draft", draft, "manual_reconcile")
        p = store.touch(c, p, "人工核对并同步草稿输入，仍需三类复核")
        return {"item": draft_detail(store, c, p), "project": p}
