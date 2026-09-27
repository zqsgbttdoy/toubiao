"""项目内容、不可变来源版本、候选条款与人工确认。"""
import re
from fastapi import APIRouter, File, Form, Request, UploadFile

from .core import DomainError, uid
from .files import parse_and_store, read_upload_sync
from .schemas import (ProjectCreate, ProjectUpdate, Archive, Selection, Version, EntityVersion,
                      Excerpt, RequirementCreate, RequirementUpdate)

router = APIRouter(prefix="/api/projects", tags=["项目与招标分析"])

# 候选条款分类关键词：命中即归入对应 category，仅用于人工确认前的初筛。
# 说明：category=="mandatory" 不等同强制条款；是否阻断复核由下方 mandatory 标志
# （必须/应当/不得/否决/废标/强制等义务词）单独判定，扩充行业词不会误升为阻断项。
PATTERNS = [
    # 资格类：企业资质、人员资格、业绩、独立性与TIS机构资格
    ("qualification", r"资质|资格|证书|注册|业绩|执业|监理资质|综合资质|专业甲级|专业乙级|"
                      r"注册监理工程师|总监资格|安全生产许可证|ISO认证|风险管理机构|TIS机构|IDI|"
                      r"注册执业资格|工程建设经历|独立性"),
    # 强制类：监理法定动作、危大工程、TIS风险管控与独立性红线
    ("mandatory", r"必须|应当|不得|否决|废标|不接受|强制|旁站监理|旁站|平行检验|见证取样|"
                  r"隐蔽工程验收|监理规划|监理实施细则|工程暂停令|竣工验收|危大工程|专项方案论证|"
                  r"风险识别|风险分级|检查频次|关键节点|整改跟踪|闭环管理|报告制度|实名制|IDI平台|"
                  r"不得兼任|独立性承诺|关联关系|参建单位"),
    # 评分类：技术标评分项、监控措施与技术创新亮点
    ("scoring", r"评分|得分|加分|分值|评审|监理大纲|质量控制措施|进度控制措施|投资控制措施|"
                r"安全管理措施|合同管理|组织协调|重难点分析|BIM应用|智慧工地|绿色监理|检测设备|"
                r"全生命周期|红外成像|无人机巡查|卫星遥感|BIM技术|大数据分析|风险减量|保险理赔"),
    # 交付/时效类：成果交付、检查整改与TIS报告时效
    ("delivery", r"交付|提交|成果|报告|节点|期限|检查|整改|时效|12小时|24小时|"
                 r"严重技术风险|重大技术风险|一般技术风险"),
    # 报价类：人月单价、费率、服务周期与评标基准价
    ("pricing", r"报价|费用|单价|税率|人月|保费|付款|结算|人月单价|监理费率|服务周期|"
                r"报价偏差率|评标基准价"),
]


def candidates(store, c, document):
    result = []
    if document["parse_status"] != "parsed":
        return result
    for block in document["blocks"]:
        for sentence in re.split(r"(?<=[。；;\n])", block["text"]):
            sentence = sentence.strip()
            if not sentence:
                continue
            categories = [category for category, pattern in PATTERNS if re.search(pattern, sentence)]
            if not categories:
                continue
            mandatory = bool(re.search(r"必须|应当|不得|否决|废标|强制", sentence))
            category = "mandatory" if mandatory else categories[0]
            item = store.save(c, "requirement", {
                "id": uid(), "project_id": document["project_id"], "text": sentence[:20000],
                "original_text": sentence[:20000], "source_text_truncated": len(sentence) > 20000,
                "category": category, "detected_categories": categories,
                "mandatory": mandatory, "confirmed": False, "response_status": "pending",
                "response_note": "", "section_id": None, "proof_material_ids": [],
                "document_id": document["id"], "block_id": block["id"], "source_version": document["source_version"],
                "source_note": document["title"], "locator": block["locator"], "origin": "local_rule_candidate"})
            result.append(item)
            if len(result) >= 1000:
                return result
    return result


def create_document(store, c, p, title, parsed, file_id=None, replaces=None, source_note="上传原件"):
    previous = store.child(c, "document", replaces, p["id"]) if replaces else None
    family = previous["source_family_id"] if previous else uid()
    family_documents = [d for d in store.all(c, "document", p["id"]) if d["source_family_id"] == family]
    source_version = max((d["source_version"] for d in family_documents), default=0) + 1
    doc = store.save(c, "document", {"id": uid(), "project_id": p["id"], "title": title,
        "file_id": file_id, "source_family_id": family, "source_version": source_version,
        "replaces_document_id": replaces, "source_note": source_note,
        "source_type": "addendum" if replaces else ("upload" if file_id else "manual_excerpt"), **parsed})
    requirements = candidates(store, c, doc)
    if len(requirements) >= 1000:
        doc["warnings"].append("候选条款达到1000条上限，请人工核对其余原文。")
        doc = store.save(c, "document", doc)
    if "source_completeness" in p.get("facts", {}):
        p["facts"]["source_completeness"]["confirmed"] = False
    p = store.touch(c, p, "招标来源或补遗发生变化")
    return {"item": doc, "project": p, "requirements": requirements}


@router.get("")
def project_list(request: Request, archived: bool | None = None, q: str = ""):
    store = request.app.state.store
    with store.transaction() as c:
        items = store.all(c, "project")
    if archived is not None:
        items = [p for p in items if p["archived"] == archived]
    if q:
        items = [p for p in items if q.casefold() in p["name"].casefold()]
    return {"items": items}


@router.post("", status_code=201)
def project_create(body: ProjectCreate, request: Request):
    store = request.app.state.store
    with store.transaction() as c:
        item = store.save(c, "project", {"id": uid(), **body.model_dump(mode="json"), "archived": False,
            "is_demo": False, "review_status": "pending", "current_review_id": None,
            "current_draft_id": None, "review_invalidated_reason": "尚未复核",
            "selected_template_ids": ["builtin-" + body.business_type, "builtin-commercial", "builtin-qualification", "builtin-response", "builtin-internal"],
            "selected_material_ids": [], "selected_snippet_ids": []})
        return {"item": item}


@router.get("/{project_id}")
def project_detail(project_id: str, request: Request):
    from .drafts import draft_detail
    from .exports import export_summary
    from .review import check_risks
    store = request.app.state.store
    with store.transaction() as c:
        p = store.project(c, project_id)
        # 导出历史仅返回摘要；完整冻结快照体积巨大，按需通过 GET /exports/{id} 获取。
        return {"item": p, "documents": store.all(c, "document", project_id),
            "requirements": store.all(c, "requirement", project_id), "quote": store.get(c, "quote", project_id, False),
            "draft": draft_detail(store, c, p), "risk_report": check_risks(store, c, p),
            "review_records": store.all(c, "review_decision", project_id),
            "exports": [export_summary(e) for e in store.all(c, "export", project_id)]}


@router.put("/{project_id}")
def project_update(project_id: str, body: ProjectUpdate, request: Request):
    store = request.app.state.store
    with store.transaction() as c:
        p = store.project(c, project_id, body.expected_version, True)
        if p["business_type"] != body.business_type and p.get("current_draft_id"):
            raise DomainError("BUSINESS_TYPE_LOCKED", "已有草稿的项目不能变更业务类型，请新建项目", 409)
        old_business = p["business_type"]
        p.update(body.model_dump(mode="json", exclude={"expected_version"}))
        if old_business != p["business_type"]:
            p["selected_template_ids"] = ["builtin-" + p["business_type"], "builtin-commercial", "builtin-qualification", "builtin-response", "builtin-internal"]
        return {"item": store.touch(c, p, "项目事实发生变化")}


@router.post("/{project_id}/archive")
def project_archive(project_id: str, body: Archive, request: Request):
    store = request.app.state.store
    with store.transaction() as c:
        p = store.project(c, project_id, body.expected_version)
        p["archived"] = body.archived
        return {"item": store.touch(c, p, "项目归档状态发生变化")}


@router.delete("/{project_id}")
def project_delete(project_id: str, body: Version, request: Request):
    store = request.app.state.store
    with store.transaction() as c:
        p = store.project(c, project_id, body.expected_version)
        if not p["archived"]:
            raise DomainError("ARCHIVE_FIRST", "删除前请先归档项目", 409)
        # 删除仅移除项目入口；历史证据、附件和不可变导出仍留在本地审计及备份中。
        store.delete(c, "project", project_id)
        return {"deleted": True, "message": "项目入口已删除，历史证据仍保留在本机备份与修订历史中"}


@router.put("/{project_id}/selection")
def project_selection(project_id: str, body: Selection, request: Request):
    store = request.app.state.store
    with store.transaction() as c:
        p = store.project(c, project_id, body.expected_version, True)
        for kind, ids in [("template", body.template_ids), ("material", body.material_ids), ("snippet", body.snippet_ids)]:
            for entity_id in ids:
                resource = store.get(c, kind, entity_id)
                if p["business_type"] not in resource["business_types"]:
                    raise DomainError("BUSINESS_SCOPE_MISMATCH", "所选模板或资料不适用于当前业务类型", 422)
            p[f"selected_{kind}_ids"] = list(dict.fromkeys(ids))
        used = {mid for r in store.all(c, "requirement", project_id) for mid in r["proof_material_ids"]}
        if not used.issubset(set(body.material_ids)):
            raise DomainError("PROOF_IN_USE", "请先解除需求证明材料关联，再从选用资料中移除", 409)
        return {"item": store.touch(c, p, "选用模板与资料发生变化")}


@router.get("/{project_id}/documents")
def documents(project_id: str, request: Request):
    store = request.app.state.store
    with store.transaction() as c:
        p = store.project(c, project_id)
        return {"items": store.all(c, "document", project_id), "project_version": p["version"]}


@router.post("/{project_id}/documents", status_code=201)
def document_upload(project_id: str, request: Request, file: UploadFile = File(...),
                    expected_version: int = Form(..., ge=1), replaces_document_id: str | None = Form(None)):
    # 同步 def：FastAPI 自动放入线程池，事务与解析不阻塞事件循环。
    store = request.app.state.store
    with store.transaction() as c:
        store.project(c, project_id, expected_version, True)
    name, extension, raw = read_upload_sync(file, store.settings)
    imported = parse_and_store(store, name, extension, raw, "tender")
    with store.transaction() as c:
        p = store.project(c, project_id, expected_version, True)
        parsed = {k: imported[k] for k in ("blocks", "page_count", "parse_status", "warnings")}
        return create_document(store, c, p, name, parsed, imported["id"], replaces_document_id)


@router.post("/{project_id}/documents/excerpts", status_code=201)
def manual_excerpt(project_id: str, body: Excerpt, request: Request):
    store = request.app.state.store
    with store.transaction() as c:
        p = store.project(c, project_id, body.expected_version, True)
        parsed = {"blocks": [{"id": uid(), "text": body.text,
                  "locator": {"kind": "manual", "note": body.source_note}}], "page_count": None,
                  "parse_status": "parsed", "warnings": ["人工摘录不等于原件完整内容，请人工核对。"]}
        return create_document(store, c, p, body.title, parsed, replaces=body.replaces_document_id, source_note=body.source_note)


@router.get("/{project_id}/documents/{document_id}")
def document_detail(project_id: str, document_id: str, request: Request):
    store = request.app.state.store
    with store.transaction() as c:
        store.project(c, project_id)
        return {"item": store.child(c, "document", document_id, project_id)}


@router.get("/{project_id}/requirements")
def requirements(project_id: str, request: Request):
    store = request.app.state.store
    with store.transaction() as c:
        p = store.project(c, project_id)
        return {"items": store.all(c, "requirement", project_id), "project_version": p["version"]}


def sync_requirement_sections(store, c, p, requirement_id, section_id):
    changed = False
    for section in store.all(c, "section", p["id"]):
        if section["draft_id"] != p.get("current_draft_id"):
            continue
        links = [rid for rid in section["requirement_ids"] if rid != requirement_id]
        if section["id"] == section_id:
            links.append(requirement_id)
        if set(links) != set(section["requirement_ids"]):
            section["requirement_ids"] = links
            store.save(c, "section", section, "requirement_link_changed")
            changed = True
    if changed:
        store.save(c, "draft", store.get(c, "draft", p["current_draft_id"]), "requirement_link_changed")


def sync_requirement_sections_bulk(store, c, project, moves: dict[str, str | None]) -> bool:
    """批量同步条款归属：moves 为 {requirement_id: 目标section_id 或 None}。

    整批只扫描一次当前草稿章节，且草稿最多保存一次，
    避免逐条同步时 O(N×S) 的重复读写与修订膨胀。返回是否有章节发生变化。
    """
    draft_id = project.get("current_draft_id")
    if not moves or not draft_id:
        return False
    incoming = {}
    for requirement_id, section_id in moves.items():
        if section_id:
            incoming.setdefault(section_id, []).append(requirement_id)
    changed = False
    for section in store.all(c, "section", project["id"]):
        if section["draft_id"] != draft_id:
            continue
        links = [rid for rid in section["requirement_ids"] if rid not in moves]
        links.extend(rid for rid in incoming.get(section["id"], []) if rid not in links)
        if set(links) != set(section["requirement_ids"]):
            section["requirement_ids"] = links
            store.save(c, "section", section, "requirement_link_changed")
            changed = True
    if changed:
        store.save(c, "draft", store.get(c, "draft", draft_id), "requirement_link_changed")
    return changed


def requirement_data(store, c, p, body):
    data = body.model_dump(mode="json", exclude={"expected_version", "entity_version"})
    if body.document_id:
        doc = store.child(c, "document", body.document_id, p["id"])
        block = next((x for x in doc["blocks"] if x["id"] == body.block_id), None)
        if not block:
            raise DomainError("SOURCE_BLOCK_MISSING", "原文定位块不存在", 422)
        data.update(original_text=block["text"][:20000], source_text_truncated=len(block["text"]) > 20000,
                    locator=block["locator"], source_version=doc["source_version"])
    else:
        data.update(original_text=body.text, source_text_truncated=False,
                    locator={"kind": "manual", "note": body.source_note}, source_version=1)
    if body.section_id:
        section = store.child(c, "section", body.section_id, p["id"])
        if section["draft_id"] != p.get("current_draft_id"):
            raise DomainError("OLD_DRAFT_SECTION", "不能关联旧稿章节", 409)
    for material_id in body.proof_material_ids:
        material = store.get(c, "material", material_id)
        if p["business_type"] not in material["business_types"]:
            raise DomainError("BUSINESS_SCOPE_MISMATCH", "证明资料业务类型不适用", 422)
        if material_id not in p["selected_material_ids"]:
            p["selected_material_ids"].append(material_id)
    return data


@router.post("/{project_id}/requirements", status_code=201)
def requirement_create(project_id: str, body: RequirementCreate, request: Request):
    store = request.app.state.store
    with store.transaction() as c:
        p = store.project(c, project_id, body.expected_version, True)
        data = requirement_data(store, c, p, body)
        item = store.save(c, "requirement", {"id": uid(), "project_id": project_id, **data, "origin": "manual"})
        sync_requirement_sections(store, c, p, item["id"], item.get("section_id"))
        return {"item": item, "project": store.touch(c, p, "需求已新增")}


@router.put("/{project_id}/requirements/{requirement_id}")
def requirement_update(project_id: str, requirement_id: str, body: RequirementUpdate, request: Request):
    store = request.app.state.store
    with store.transaction() as c:
        p = store.project(c, project_id, body.expected_version, True)
        item = store.child(c, "requirement", requirement_id, project_id)
        store.expect(item, body.entity_version)
        data = requirement_data(store, c, p, body)
        item = store.save(c, "requirement", {**item, **data})
        sync_requirement_sections(store, c, p, item["id"], item.get("section_id"))
        return {"item": item, "project": store.touch(c, p, "需求及人工确认发生变化")}


@router.delete("/{project_id}/requirements/{requirement_id}")
def requirement_delete(project_id: str, requirement_id: str, body: EntityVersion, request: Request):
    store = request.app.state.store
    with store.transaction() as c:
        p = store.project(c, project_id, body.expected_version, True)
        item = store.child(c, "requirement", requirement_id, project_id)
        store.expect(item, body.entity_version)
        store.delete(c, "requirement", requirement_id)
        sync_requirement_sections(store, c, p, requirement_id, None)
        return {"deleted": True, "project": store.touch(c, p, "需求已删除，请核对是否遗漏条款")}
