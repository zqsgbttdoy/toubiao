"""规则模板组装、输入快照、章节修订与来源版本追溯。"""
import hashlib
import re
from fastapi import APIRouter, Request

from .core import DomainError, dumps, now, uid
from .pricing import quote_text
from .schemas import Generate, SectionEdit, InsertSnippet, ReconcileDraft

router = APIRouter(prefix="/api/projects", tags=["章节草稿"])
# 草稿列表只返回元数据；input_snapshot 与各章节正文仅通过 GET /drafts/{id} 获取。
DRAFT_SUMMARY_KEYS = ("id", "project_id", "version", "generation", "previous_draft_id",
                      "input_project_version", "input_hash", "generation_method",
                      "created_at", "updated_at")

# 标准化编制指引：按“模板ID:章节key”索引，仅对监理大纲14章与TIS方案11章注入。
# 指引在草稿生成时插入到章节正文之前，为编制人提供评分对应、要点清单、
# 建议字数与评分要点；仅降低操作门槛，不代替人工编制与复核。
SECTION_GUIDANCE = {
    "builtin-supervision-outline:ch01": "【编制指引】本章为技术标基础项，需重点描述：\n1. 项目基本信息（名称、地点、规模、投资、工期、结构形式）\n2. 建设内容与招标范围\n3. 工程特点与技术难点初步识别\n4. 参建单位（建设、勘察、设计、施工）\n建议字数：800-1500字。要点：信息须与招标文件一致，体现对本工程的针对性认识，不得照搬通用模板。",
    "builtin-supervision-outline:ch02": "【编制指引】需重点描述：\n1. 监理范围界定（阶段、专业、区域边界）\n2. 服务内容（质量、进度、造价、安全、合同、信息、组织协调）\n3. 服务阶段划分（施工准备、施工实施、竣工验收、保修）\n建议字数：1000-1800字。要点：范围须与招标委托范围严格一致，杜绝超范围或漏项承诺。",
    "builtin-supervision-outline:ch03": "【编制指引】需重点描述：\n1. 质量目标（合格/优良/创杯）\n2. 进度目标（总工期与关键节点）\n3. 投资目标（控制在批复概算内）\n4. 安全与环保文明施工目标\n建议字数：600-1200字。要点：目标须量化、可考核，并逐项对应合同与招标要求。",
    "builtin-supervision-outline:ch04": "【编制指引】需重点描述：\n1. 法律法规与部门规章\n2. 技术标准与规范（列出本工程适用清单）\n3. 合同文件（施工、监理合同、招标文件）\n4. 设计文件（施工图、图纸会审纪要）\n建议字数：800-1500字。要点：依据须现行有效、完整，体现本工程针对性。",
    "builtin-supervision-outline:ch05": "【编制指引】需重点描述：\n1. 组织形式与机构设置\n2. 人员配置与岗位职责\n3. 人员进退场计划\n4. 监理工作制度（例会、报告、见证、旁站等）\n建议字数：1500-2500字。要点：须与人员进场表、机构组成表及社保/证书附件一致，评分关注配置合理性。",
    "builtin-supervision-outline:ch06": "【编制指引】本章节对应评分项“质量控制措施”（约9分），需重点描述：\n1. 质量控制目标与验收标准\n2. 施工准备阶段质量控制（图纸会审、方案审批、材料验收）\n3. 施工过程控制方法（巡视、旁站、平行检验、见证取样的频次和记录要求）\n4. 隐蔽工程验收流程\n5. 分部分项验收与质量缺陷处理\n6. 重点部位专项措施（基础、主体、防水、幕墙等）\n建议字数：3000-5000字。评分要点：措施具体可操作、有量化指标、体现本工程针对性。",
    "builtin-supervision-outline:ch07": "【编制指引】本章节对应评分项“投资/造价控制措施”（约5分），需重点描述：\n1. 造价控制目标与原则\n2. 工程计量与支付审核流程\n3. 变更管理与签证控制\n4. 索赔管理\n5. 竣工结算审核\n建议字数：1500-2500字。评分要点：控制流程清晰、有量化把关节点。",
    "builtin-supervision-outline:ch08": "【编制指引】本章节对应评分项“进度控制措施”（约5分），需重点描述：\n1. 进度控制目标与原则\n2. 进度计划审批\n3. 监控方法（横道图、网络图、S曲线）\n4. 进度偏差分析与纠偏\n5. 关键线路管理\n建议字数：1500-2500字。评分要点：方法得当、有预警与纠偏机制。",
    "builtin-supervision-outline:ch09": "【编制指引】本章节对应评分项“安全生产管理措施”（约9分），需重点描述：\n1. 安全目标与责任体系\n2. 安全监理工作内容与巡查频次\n3. 危大工程管理（专项方案审查与论证、旁站）\n4. 应急预案与演练\n5. 文明施工与扬尘治理\n建议字数：3000-5000字。评分要点：危大工程管控具体、责任界面清晰、不代替施工单位安全责任。",
    "builtin-supervision-outline:ch10": "【编制指引】本章节对应评分项“合同管理措施”（约4分），需重点描述：\n1. 合同管理体系\n2. 履约监控\n3. 合同变更管理\n4. 争议协调\n5. 合同档案管理\n建议字数：1000-1800字。评分要点：体系完整、流程可执行。",
    "builtin-supervision-outline:ch11": "【编制指引】需重点描述：\n1. 信息管理制度\n2. 监理文件资料清单\n3. 信息传递流程\n4. 信息化工具（智慧工地、监理软件）\n5. 资料归档与移交\n建议字数：1000-1800字。要点：体现规范化与信息化水平，交付清单须与合同约定一致。",
    "builtin-supervision-outline:ch12": "【编制指引】本章节对应评分项“组织协调措施”（约3分），需重点描述：\n1. 协调机制（监理例会、专题协调会）\n2. 与建设单位的协调\n3. 与施工、设计单位的协调\n4. 与政府部门、周边社区的协调\n建议字数：1000-1800字。评分要点：机制健全、界面清晰、方法具体。",
    "builtin-supervision-outline:ch13": "【编制指引】需重点描述：\n1. 办公设施\n2. 检测设备清单（回弹仪、钢筋扫描仪、全站仪、水准仪、保护层测定仪等）\n3. 交通工具\n4. 信息化设备\n建议字数：600-1200字。要点：设备须在检定/校准有效期内，配置与检测设备清单表一致，体现履约能力。",
    "builtin-supervision-outline:ch14": "【编制指引】本章节对应评分项“本工程重难点分析与应对措施”（约6分），需重点描述：\n1. 技术重难点识别与分析\n2. 管理重难点分析\n3. 针对性应对措施\n4. BIM应用\n5. 绿色监理与智慧工地\n建议字数：2500-4000字。评分要点：重难点识别准确、措施针对性强、体现方案深度与本工程特点。",
    "builtin-tis-plan:s01": "【编制指引】需重点描述：\n1. TIS角色定位（独立第三方技术服务）\n2. 服务对象（建设单位/保险公司）\n3. 服务目标（风险识别与减量）\n4. 与监理、设计审查、法定检测及保险核保理赔的边界\n建议字数：800-1500字。要点：边界清晰，不代替其他主体责任，独立性表述准确。",
    "builtin-tis-plan:s02": "【编制指引】需重点描述全生命周期6阶段服务：\n1. 勘察阶段\n2. 设计阶段\n3. 施工阶段\n4. 竣工阶段\n5. 回访阶段\n6. 理赔辅助阶段\n各阶段工作内容与交付成果。建议字数：2000-3500字。要点：技术服务费不与保费混写，人月与检查次数分别记录。",
    "builtin-tis-plan:s03": "【编制指引】需重点描述：\n1. 组织架构\n2. 风险管理负责人资格（15年以上工程建设经历+注册执业资格）\n3. 风险管理工程师配置\n4. 专业专家库\n5. 独立性承诺\n建议字数：1200-2000字。要点：负责人资格须达标并可佐证，独立性与角色兼任须按项目所在地规则核对。",
    "builtin-tis-plan:s04": "【编制指引】需重点描述：\n1. 风险识别方法\n2. 风险分类\n3. 三级分级标准（严重/重大/一般技术风险）\n4. 风险清单\n建议字数：1500-2500字。要点：分级标准明确、可操作，与报告时效和上报机制衔接。",
    "builtin-tis-plan:s05": "【编制指引】需重点描述：\n1. 施工阶段各分项检查频次\n2. 7个关键必检节点\n3. 检测数量不低于5%等要求\n建议字数：1000-1800字。要点：节点与频次结合本项目实际，不默认通用，须与检查节点计划表一致。",
    "builtin-tis-plan:s06": "【编制指引】需重点描述闭环流程：\n1. 检查前准备\n2. 现场检查\n3. 问题记录\n4. 沟通反馈\n5. 报告编制\n6. 整改跟踪\n建议字数：1200-2000字。要点：每步留痕可追溯，责任界面清晰。",
    "builtin-tis-plan:s07": "【编制指引】需重点描述：\n1. 6类报告及内容要求\n2. 报告时效（不合格12小时内通知、合格24小时内通知、严重技术风险立即电话+24小时书面）\n3. IDI平台上传\n建议字数：1200-2000字。要点：时效表述准确，与合同及项目所在地规则一致。",
    "builtin-tis-plan:s08": "【编制指引】需重点描述：\n1. 整改通知单\n2. 整改方案审核\n3. 过程跟踪\n4. 复查验证\n5. 闭环确认\n6. 拒不整改处理机制\n建议字数：1000-1800字。要点：形成可追溯闭环记录，未闭环事项持续跟踪。",
    "builtin-tis-plan:s09": "【编制指引】需重点描述：\n1. 红外成像\n2. 无人机巡查\n3. 卫星遥感\n4. 内窥镜/X光检测\n5. BIM技术\n6. 大数据分析\n建议字数：1000-2000字。要点：技术应用须结合本工程风险点，说明实际减量效果，避免堆砌概念。",
    "builtin-tis-plan:s10": "【编制指引】需重点描述：\n1. 内部管理制度\n2. 人员培训考核\n3. 设备校准\n4. 过程记录\n5. 满意度评价\n6. 持续改进\n建议字数：800-1500字。要点：制度可落地、记录可核查。",
    "builtin-tis-plan:s11": "【编制指引】需重点描述：\n1. 独立性承诺\n2. 廉洁自律\n3. 保密义务\n4. 合规经营（不转包、不违规低价）\n建议字数：600-1200字。要点：承诺具体、可追责，独立性须按项目所在地规则人工核对。",
}


def with_guidance(template_key, body):
    """为特定章节在正文前插入标准化编制指引；无对应指引时原样返回。"""
    guidance = SECTION_GUIDANCE.get(template_key)
    return guidance + "\n\n" + body if guidance else body


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


def draft_detail(store, c, p, draft_id=None, current_hash=None):
    draft_id = draft_id or p.get("current_draft_id")
    if not draft_id:
        return None
    draft = store.child(c, "draft", draft_id, p["id"])
    return {**draft, "sections": current_sections(store, c, p, draft_id),
            "stale": draft["input_hash"] != (current_hash or fingerprint(input_snapshot(store, c, p))),
            "is_current": draft_id == p.get("current_draft_id")}


def draft_summaries(store, c, p, current_hash=None):
    """草稿列表摘要：一次指纹计算与一次章节扫描，不回传快照与正文。"""
    current_hash = current_hash or fingerprint(input_snapshot(store, c, p))
    counts = {}
    for section in store.all(c, "section", p["id"]):
        counts[section["draft_id"]] = counts.get(section["draft_id"], 0) + 1
    summaries = []
    for draft in store.all(c, "draft", p["id"]):
        summary = {key: draft.get(key) for key in DRAFT_SUMMARY_KEYS}
        summary.update(stale=draft["input_hash"] != current_hash,
                       is_current=draft["id"] == p.get("current_draft_id"),
                       section_count=counts.get(draft["id"], 0))
        summaries.append(summary)
    return summaries


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
        current_hash = fingerprint(input_snapshot(store, c, p))
        return {"items": draft_summaries(store, c, p, current_hash),
                "current": draft_detail(store, c, p, current_hash=current_hash),
                "project_version": p["version"]}


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
                    "body": with_guidance(key, render(part["body"], snapshot)), "manually_edited": False,
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
        from .projects import sync_requirement_sections_bulk
        # 先汇总全部归属变更，再一次性同步章节关联，避免逐条 O(N×S) 写入。
        moves = {}
        for requirement in store.all(c, "requirement", project_id):
            target = section_id if requirement["id"] in body.requirement_ids else requirement.get("section_id")
            if requirement["id"] not in body.requirement_ids and target == section_id:
                target = None
            if target != requirement.get("section_id"):
                requirement["section_id"] = target
                store.save(c, "requirement", requirement, "section_editor_link")
                moves[requirement["id"]] = target
        sync_requirement_sections_bulk(store, c, p, moves)
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
