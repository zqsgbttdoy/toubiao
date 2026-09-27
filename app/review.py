"""风险分层、三类人工记录及不可变内部复核快照。"""
from datetime import date, datetime
from decimal import Decimal
import re
from fastapi import APIRouter, Request

from .core import DomainError, now, uid
from .drafts import current_sections, draft_detail, fingerprint, input_snapshot
from .files import blob_bytes
from .pricing import quote_text
from .schemas import ReviewDecision, FinalizeReview

router = APIRouter(prefix="/api/projects", tags=["风险与内部复核"])
DISCLAIMER = "本地规则仅报告风险，不代替法律判断；审核人只是人工记录，无身份认证，不能保证合规、中标或可直接提交。"
# 复核列表只返回冻结快照摘要；完整不可变快照通过 GET /review/snapshots/{id} 获取。
SNAPSHOT_SUMMARY_KEYS = ("id", "project_id", "version", "created_at", "updated_at",
                         "project_version", "reviewer", "immutable")


def snapshot_summary(record):
    summary = {key: record.get(key) for key in SNAPSHOT_SUMMARY_KEYS}
    summary["frozen_at"] = (record.get("snapshot") or {}).get("frozen_at")
    return summary


def referenced_file_ids(store, c, p, inputs):
    file_ids = {fid for m in inputs["materials"] for fid in m["file_ids"]}
    file_ids.update(s["source_file_id"] for s in inputs["snippets"])
    file_ids.update(d["file_id"] for d in inputs["documents"] if d.get("file_id"))
    for section in current_sections(store, c, p):
        for ref in section["references"]:
            revision = store.get_version(c, ref["kind"], ref["id"], ref["version"])
            if not revision:
                continue
            if ref["kind"] == "material":
                file_ids.update(revision.get("file_ids", []))
            elif ref["kind"] == "snippet":
                file_ids.add(revision["source_file_id"])
            elif ref["kind"] == "document" and revision.get("file_id"):
                file_ids.add(revision["file_id"])
    return file_ids


def check_risks(store, c, p):
    issues = []
    def add(code, message, category="blocking", entity_id=None):
        issues.append({"code": code, "message": message, "severity": category,
                       "blocking": category == "blocking", "entity_id": entity_id})
    snapshot = input_snapshot(store, c, p)
    sections = current_sections(store, c, p)
    section_ids = {s["id"] for s in sections}
    if not snapshot["documents"]:
        add("SOURCE_MISSING", "尚无招标原文或人工摘录来源")
    if not snapshot["requirements"]:
        add("REQUIREMENTS_EMPTY", "未发现要求不等于满足要求，请人工录入并确认条款")
    for field, label in [("region", "地区"), ("client", "委托方"), ("scope", "服务范围"), ("deadline", "投标截止时间")]:
        if not p.get(field):
            add("PROJECT_FIELD_MISSING", f"项目缺少{label}")
    if p.get("deadline") and datetime.fromisoformat(p["deadline"]) < datetime.now().astimezone():
        add("DEADLINE_PASSED", "投标截止时间已过，请人工核对", "information")
    for doc in snapshot["documents"]:
        if doc["parse_status"] != "parsed" or any("部分PDF" in w or "1000条" in w for w in doc["warnings"]):
            fact = p["facts"].get("source_completeness", {})
            if not fact.get("confirmed"):
                add("SOURCE_INCOMPLETE", "文档存在无文字、低质量或截断内容，需人工摘录并确认source_completeness事实", entity_id=doc["id"])
    for r in snapshot["requirements"]:
        if not r["confirmed"]:
            add("REQUIREMENT_UNCONFIRMED", "条款尚未人工确认：" + r["text"][:70], entity_id=r["id"])
        if r["mandatory"] and (r["response_status"] != "responded" or not r["response_note"].strip()):
            add("MANDATORY_UNANSWERED", "强制条款未明确响应并说明：" + r["text"][:70], entity_id=r["id"])
        if r["mandatory"] and r.get("section_id") not in section_ids:
            add("MANDATORY_SECTION_MISSING", "强制条款未映射当前草稿章节", entity_id=r["id"])
        if (r["category"] == "qualification" or "qualification" in r.get("detected_categories", [])) and r["mandatory"] and not r["proof_material_ids"]:
            add("MANDATORY_PROOF_MISSING", "强制资格条款缺少证明资料关联", entity_id=r["id"])
        if r["category"] == "scoring" and r["response_status"] != "responded":
            add("SCORING_GAP", "评分点尚未响应，可能影响得分", "scoring", r["id"])
        if not r["mandatory"] and r["category"] != "scoring" and r["response_status"] in ("pending", "gap"):
            add("RESPONSE_GAP", "非强制条款尚有响应缺口", "information", r["id"])
    if not sections:
        add("DRAFT_MISSING", "尚未生成草稿")
    present = {s["category"] for s in sections}
    for category, label in [("technical", "技术"), ("commercial", "商务"), ("qualification", "资质"), ("response", "响应表"), ("internal", "内部复核表")]:
        if category not in present:
            add("SECTION_MISSING", f"缺少{label}章节")
    required_facts = ["regional_rules"]
    if p["business_type"] == "tis":
        required_facts += ["commission_relationship", "independence", "inspection_nodes", "risk_process", "staffing"]
    for key in required_facts:
        if not p["facts"].get(key, {}).get("confirmed"):
            add("REGIONAL_RULES_UNCONFIRMED" if key == "regional_rules" else "TIS_BOUNDARY_UNCONFIRMED",
                f"需人工确认项目事实：{key}；地区规则不作全国自动判断")
    requirements_by_id = {r["id"]: r for r in snapshot["requirements"]}
    for section in sections:
        if not section["body"].strip() or re.search(r"【待填|\{\{|TODO|待补充|待填写", section["body"], re.I):
            add("PLACEHOLDER", "章节存在空白或待填内容：" + section["title"], entity_id=section["id"])
        for rid in section["requirement_ids"]:
            if rid not in requirements_by_id:
                add("REQUIREMENT_LINK_BROKEN", "章节关联了已删除需求", entity_id=section["id"])
        for ref in section["references"]:
            resource = store.get(c, ref["kind"], ref["id"], False)
            if not resource or resource["version"] != ref["version"]:
                add("SOURCE_VERSION_STALE", "章节引用来源版本已变化，需要重新核对或生成", entity_id=section["id"])
    draft = store.get(c, "draft", p["current_draft_id"], False) if p.get("current_draft_id") else None
    if draft and draft["input_hash"] != fingerprint(snapshot):
        add("DRAFT_STALE", "草稿输入已过期，请重新生成或人工逐章核对后同步输入快照")
    deadline_date = datetime.fromisoformat(p["deadline"]).date() if p.get("deadline") else date.today()
    relevant_date = max(date.today(), deadline_date)
    if not snapshot["materials"]:
        add("MATERIALS_MISSING", "未选择企业证明资料")
    file_ids = referenced_file_ids(store, c, p, snapshot)
    for m in snapshot["materials"]:
        if m["review_status"] != "approved" or not m.get("verification") or m["verification"].get("content_version") != m["version"]:
            add("MATERIAL_UNVERIFIED", "资料尚未针对当前版本人工核验：" + m["name"], entity_id=m["id"])
        if not m.get("scope") or p["business_type"] not in m["business_types"]:
            add("MATERIAL_SCOPE", "资料适用范围缺失或业务类型不匹配：" + m["name"], entity_id=m["id"])
        if m.get("valid_until") and date.fromisoformat(m["valid_until"]) < relevant_date:
            add("CERTIFICATE_EXPIRED", "证照在当前或截止时点已过期：" + m["name"], entity_id=m["id"])
        if m.get("valid_from") and date.fromisoformat(m["valid_from"]) > date.today():
            add("CERTIFICATE_NOT_YET_VALID", "证照尚未生效：" + m["name"], entity_id=m["id"])
        if not m.get("valid_until") and not m.get("validity_note"):
            add("VALIDITY_UNKNOWN", "缺少有效期或长期有效/业绩性质说明：" + m["name"], entity_id=m["id"])
        if not m["file_ids"]:
            add("ATTACHMENT_MISSING", "资料没有原始证明附件：" + m["name"], entity_id=m["id"])
        file_ids.update(m["file_ids"])
    for template in snapshot["templates"]:
        if template["review_status"] != "approved":
            add("TEMPLATE_UNREVIEWED", "模板尚未人工审核，仅作参考：" + template["name"], "information", template["id"])
    for snippet in snapshot["snippets"]:
        file_ids.add(snippet["source_file_id"])
        if snippet["review_status"] != "approved":
            add("SNIPPET_UNVERIFIED", "历史素材尚未核验，不可视为项目事实：" + snippet["title"], "information", snippet["id"])
    for doc in snapshot["documents"]:
        if doc.get("file_id"):
            file_ids.add(doc["file_id"])
    for file_id in file_ids:
        try:
            blob_bytes(store, store.get(c, "file", file_id))
        except DomainError as exc:
            add(exc.code, exc.message, entity_id=file_id)
    quote = snapshot["quote"]
    if not quote or not quote.get("tax_confirmed") or Decimal(quote["total"]) <= 0:
        add("QUOTE_INCOMPLETE", "报价缺失、合计非正数或税率未明确确认")
    if draft and draft["quote_snapshot"] != quote:
        add("QUOTE_SNAPSHOT_STALE", "正文报价快照与当前报价不一致，必须重新生成")
    if quote and draft and sections and not any(s["category"] == "commercial" and s["contains_quote"] and quote_text(draft["quote_snapshot"]) in s["body"] for s in sections):
        add("QUOTE_BODY_MISSING", "商务正文缺少与草稿快照一致的完整报价块")
    return {"project_version": p["version"], "checked_at": now(), "issues": issues,
            "blocking_count": sum(x["blocking"] for x in issues),
            "scoring_count": sum(x["severity"] == "scoring" for x in issues),
            "information_count": sum(x["severity"] == "information" for x in issues),
            "can_finalize": not any(x["blocking"] for x in issues), "disclaimer": DISCLAIMER}


def frozen_snapshot(store, c, p, report):
    inputs = input_snapshot(store, c, p)
    file_ids = referenced_file_ids(store, c, p, inputs)
    return {"project": p, "inputs": inputs, "draft": draft_detail(store, c, p),
            "risk_report": report, "review_records": store.all(c, "review_decision", p["id"]),
            "files": [store.get(c, "file", fid) for fid in sorted(file_ids)], "frozen_at": now(), "disclaimer": DISCLAIMER}


@router.get("/{project_id}/review")
def review_get(project_id: str, request: Request):
    store = request.app.state.store
    with store.transaction() as c:
        p = store.project(c, project_id)
        records = store.all(c, "review_decision", project_id)
        for record in records:
            record["stale"] = record["project_version"] != p["version"]
        return {"project_version": p["version"], "status": p["review_status"],
            "records": records, "risk_report": check_risks(store, c, p),
            "current_review_id": p.get("current_review_id"),
            "snapshots": [snapshot_summary(x) for x in store.all(c, "review_snapshot", project_id)]}


@router.get("/{project_id}/review/snapshots/{snapshot_id}")
def review_snapshot_detail(project_id: str, snapshot_id: str, request: Request):
    store = request.app.state.store
    with store.transaction() as c:
        store.project(c, project_id)
        return {"item": store.child(c, "review_snapshot", snapshot_id, project_id)}


@router.post("/{project_id}/review/check")
def review_check(project_id: str, request: Request):
    store = request.app.state.store
    with store.transaction() as c:
        return {"item": check_risks(store, c, store.project(c, project_id))}


@router.put("/{project_id}/review/decisions")
def review_decision(project_id: str, body: ReviewDecision, request: Request):
    store = request.app.state.store
    with store.transaction() as c:
        p = store.project(c, project_id, body.expected_version, True)
        record_id = project_id + "_" + body.category
        old = store.get(c, "review_decision", record_id, False)
        if body.entity_version != (old["version"] if old else 0):
            raise DomainError("VERSION_CONFLICT", "人工复核记录已变化", 409)
        if p["review_status"] == "reviewed":
            p = store.touch(c, p, "人工复核意见变化，原冻结版本保留，需重新复核")
        item = store.save(c, "review_decision", {"id": record_id, "project_id": project_id,
            "project_version": p["version"], "category": body.category, "reviewer": body.reviewer,
            "opinion": body.opinion, "decision": body.decision, "recorded_at": now(), "authenticated": False})
        return {"item": item, "project": p}


@router.post("/{project_id}/review/finalize", status_code=201)
def review_finalize(project_id: str, body: FinalizeReview, request: Request):
    store = request.app.state.store
    with store.transaction() as c:
        p = store.project(c, project_id, body.expected_version, True)
        if not body.confirmation:
            raise DomainError("CONFIRMATION_REQUIRED", "须明确确认已完成人工复核", 422)
        report = check_risks(store, c, p)
        if not report["can_finalize"]:
            raise DomainError("REVIEW_BLOCKED", f"仍有{report['blocking_count']}项阻断风险，不能标记已内部复核", 409)
        records = store.all(c, "review_decision", project_id)
        for category in ("technical", "commercial", "qualification"):
            record = next((x for x in records if x["category"] == category), None)
            if not record or record["decision"] != "approved" or record["project_version"] != p["version"]:
                raise DomainError("REVIEW_RECORDS_INCOMPLETE", "技术、商务、资质三类均须有当前版本的通过意见", 409)
        snapshot_id = uid()
        p.update(review_status="reviewed", current_review_id=snapshot_id, review_invalidated_reason="")
        p = store.save(c, "project", p, "internally_reviewed")
        for record in records:
            record["project_version"] = p["version"]
            store.save(c, "review_decision", record, "bind_frozen_version")
        report["project_version"] = p["version"]
        item = store.save(c, "review_snapshot", {"id": snapshot_id, "project_id": project_id,
            "project_version": p["version"], "reviewer": body.reviewer,
            "snapshot": frozen_snapshot(store, c, p, report), "immutable": True})
        return {"item": item, "project": p}
