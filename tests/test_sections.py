"""章节类附件（P0 批次 1E）生成器测试。

独立文件自带 fixture（无 conftest.py，跨文件导入夹具不稳），覆盖监理大纲14章 / TIS方案11章：
章节数、目录、编制指引、占位符按项目事实解析且不残留花括号、materials/quote 不臆造、
目录/指引开关、业务类型隔离、输入校验与「生成不失效复核」回归护栏。
"""
import hashlib
import io
import pytest
from fastapi.testclient import TestClient
from docx import Document

from app.core import Settings
from app.main import create_app

ORIGIN = "http://127.0.0.1:8000"


@pytest.fixture
def settings(tmp_path):
    return Settings(tmp_path / "isolated_data_sections", parse_timeout=20)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings), base_url=ORIGIN, headers={"Origin": ORIGIN}) as session:
        yield session


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def new_project(client, business="supervision", facts=None):
    return ok(client.post("/api/projects", json={
        "name": "【虚构测试】章节附件项目", "business_type": business,
        "region": "示例地区", "client": "虚构委托单位", "scope": "施工阶段监理",
        "deadline": "2030-12-31T17:00:00+08:00",
        "facts": facts or {"control_points": {"value": "塔吊群作业与深基坑", "confirmed": True}}}), 201)["item"]


def gen(client, project, template_key, payload):
    return ok(client.post(f"/api/projects/{project['id']}/gendocs",
                          json={"template_key": template_key, "payload": payload}), 201)


def doc_of(client, result):
    raw = client.get(result["file"]["download_url"]).content
    return Document(io.BytesIO(raw))


def headings(doc):
    return [p.text for p in doc.paragraphs if p.style.name == "Heading 1"]


def full_text(doc):
    return "\n".join(p.text for p in doc.paragraphs)


# ─────────────────────────── 测试用例 ───────────────────────────


def test_section_templates_registered_and_business_scoped(client):
    """两个章节模板注册且按业务类型隔离，form_type=sections 附带派生字段。"""
    sup = {i["key"]: i for i in ok(client.get("/api/gendocs/templates?business_type=supervision"))["items"]}
    tis = {i["key"]: i for i in ok(client.get("/api/gendocs/templates?business_type=tis"))["items"]}
    assert "supervision-outline" in sup and "supervision-outline" not in tis
    assert "tis-plan" in tis and "tis-plan" not in sup
    fields = {f["key"] for f in sup["supervision-outline"]["fields"]}
    assert {"title", "include_toc", "include_guidance"} <= fields
    assert sup["supervision-outline"]["form_type"] == "sections"


def test_supervision_outline_structure_and_fact_resolution(client):
    """监理大纲：14 个 Heading 1 + 目录 + 编制指引；项目事实解析、无花括号残留、资料位不臆造。"""
    p = new_project(client)
    result = gen(client, p, "supervision-outline", {})
    raw = client.get(result["file"]["download_url"]).content
    assert hashlib.sha256(raw).hexdigest() == result["file"]["sha256"]
    doc = Document(io.BytesIO(raw))
    texts = headings(doc)
    assert len(texts) == 14, f"应为14章，实际 {len(texts)}"
    assert texts[0].startswith("第一章") and texts[-1].startswith("第十四章")
    body = full_text(doc)
    assert "目　录" in body and "【本章要点】" in body, "目录与编制指引默认应出现"
    assert "塔吊群作业与深基坑" in body, "已登记的 fact 应被解析进正文"
    assert "{{" not in body, "正文不应残留未替换的占位符花括号"
    assert "资料库" in body, "{{materials}} 应渲染为人工补充提示而非留空或伪造"


def test_tis_plan_has_eleven_chapters(client):
    """TIS 方案：11 章框架 + 人工补充纪律提示。"""
    p = new_project(client, business="tis")
    result = gen(client, p, "tis-plan", {})
    doc = doc_of(client, result)
    texts = headings(doc)
    assert len(texts) == 11
    assert texts[0].startswith("第一章") and texts[-1].startswith("第十一章")
    body = full_text(doc)
    assert "独立性" in body or "不代替监理" in body
    assert "{{" not in body


def test_sections_toggles_remove_toc_and_guidance(client):
    """关闭目录与编制指引后正文更精简，但章数不变。"""
    p = new_project(client)
    result = gen(client, p, "supervision-outline", {"include_toc": False, "include_guidance": False})
    doc = doc_of(client, result)
    body = full_text(doc)
    assert "目　录" not in body
    assert "【本章要点】" not in body
    assert len(headings(doc)) == 14, "关闭目录/指引不应影响章节数"


def test_sections_validation_and_review_guard(client):
    """未知字段 422；生成不改变项目版本与复核状态。"""
    p = new_project(client)
    before = ok(client.get(f"/api/projects/{p['id']}"))["item"]

    assert client.post(f"/api/projects/{p['id']}/gendocs", json={
        "template_key": "supervision-outline", "payload": {"bogus": True}}).status_code == 422

    gen(client, p, "supervision-outline", {"title": "某监理技术建议书"})
    after = ok(client.get(f"/api/projects/{p['id']}"))["item"]
    assert after["version"] == before["version"]
    assert after["review_status"] == before["review_status"]
