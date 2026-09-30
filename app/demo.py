"""手动载入的虚构资料和可重复生成的真实DOCX上传样本。"""
import io
from docx import Document

from .core import uid
from .files import _docx_blocks, store_blob
from .projects import create_document


SAMPLES = {
    "supervision": [
        "【虚构演示】青岚示例工程监理招标摘要",
        "本文件由软件生成，仅用于功能验证，不涉及真实企业、人员、证照或项目。",
        "委托方为虚构的青岚示例建设单位；地区为演示地区；服务范围为主体工程施工阶段监理。",
        "投标单位必须提供适用的监理资质证明，并提交拟派人员证照目录。",
        "监理技术方案评分关注质量、进度、造价和安全履职措施。",
        "服务期内每月提交监理报告；问题整改记录应包含复查及关闭意见。",
        "报价按人月或检查次数列明数量、单价及依据，税率须由投标人明确确认。",
        "所有信息均为虚构，示例条款须经人工确认后方可进入响应矩阵。",
    ],
    "tis": [
        "【虚构演示】云汀示例工程TIS风险减量服务招标摘要",
        "本文件仅用于上传和业务验证，不包含真实企业资质或保险产品信息。",
        "委托方为虚构的云汀示例委托单位；服务内容为示例工程质量风险识别与技术检查。",
        "TIS机构必须说明独立性、利益冲突及同项目角色边界，不得代替监理或保险核保理赔。",
        "技术评分关注风险识别、分级、整改追踪及复核关闭机制。",
        "交付报告应列明地基基础、主体结构和防水等实际适用检查节点及频次。",
        "TIS技术服务费应分列人月和检查次数，保险保费不得混入本服务报价。",
        "地区TIS规则须人工核对，不得把一个地区的规定自动视为全国要求。",
    ],
}


def synthetic_docx(business_type):
    document = Document()
    for index, text in enumerate(SAMPLES[business_type]):
        if index == 0:
            document.add_heading(text, 0)
        else:
            document.add_paragraph(text)
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "示例条款定位"
    table.cell(0, 1).text = "请核对段落与表格定位；Word页码不会被虚构。"
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


def load_demo(store):
    with store.transaction() as c:
        previous = [p for p in store.all(c, "project") if p.get("is_demo")]
        if previous:
            return {"items": previous, "already_loaded": True}
        projects = []
        for business, title in [("supervision", "【虚构演示】青岚监理项目"), ("tis", "【虚构演示】云汀TIS项目")]:
            p = store.save(c, "project", {"id": uid(), "name": title, "business_type": business,
                "region": "虚构示例地区（无实际规则适用结论）", "client": "虚构示例委托单位", "scope": "仅用于软件试用的合成服务范围",
                "deadline": "2030-12-31T17:00:00+08:00", "facts": {}, "archived": False, "is_demo": True,
                "review_status": "pending", "current_review_id": None, "current_draft_id": None,
                "review_invalidated_reason": "虚构演示，不可提交",
                "selected_template_ids": ["builtin-" + business, "builtin-commercial", "builtin-qualification", "builtin-response", "builtin-internal"],
                "selected_material_ids": [], "selected_snippet_ids": []})
            raw = synthetic_docx(business)
            blocks, _ = _docx_blocks(raw)
            parsed = {"blocks": blocks, "parse_status": "parsed", "page_count": None, "warnings": ["全部内容为虚构演示，不可用于真实投标。"]}
            file = store_blob(store, c, raw, business + "_fictional_sample.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document", parsed, "demo")
            result = create_document(store, c, p, title + "招标摘要", parsed, file["id"], source_note="明确标注的合成DOCX示例")
            material = store.save(c, "material", {"id": uid(), "name": title + "—虚构资料（非真实资质）",
                "kind": "experience", "business_types": [business], "description": "虚构试用资料，不代表任何真实企业、资质或业绩。",
                "valid_from": None, "valid_until": None, "validity_note": "虚构演示，无真实有效性",
                "scope": "仅软件演示", "file_ids": [file["id"]], "tags": ["虚构演示"], "is_demo": True,
                "review_status": "pending", "verification": None, "builtin": False})
            p = result["project"]
            p["selected_material_ids"] = [material["id"]]
            projects.append(store.touch(c, p, "已载入未核验的虚构演示资料"))
        return {"items": projects, "already_loaded": False}
