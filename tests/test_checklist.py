"""勾选类附件（P0 批次 1B）生成器测试。

独立文件自带 fixture。覆盖：无行贿犯罪声明（段落+勾选）、企业资质清单（表格+勾选列），
以及通用列式引擎的元数据下发、勾选符号、select 值→标签、输入校验、复核不失效护栏。
"""
import hashlib
import io
import pytest
from fastapi.testclient import TestClient
from docx import Document

from app.core import Settings
from app.main import create_app

ORIGIN = "http://127.0.0.1:8000"
CHECKED = "\u2611"    # ☑
UNCHECKED = "\u25a1"  # □


@pytest.fixture
def settings(tmp_path):
    return Settings(tmp_path / "isolated_data_checklist", parse_timeout=20)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings), base_url=ORIGIN, headers={"Origin": ORIGIN}) as session:
        yield session


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def new_project(client, business="supervision"):
    return ok(client.post("/api/projects", json={
        "name": "【虚构测试】勾选附件项目", "business_type": business,
        "region": "示例地区", "client": "虚构委托单位", "scope": "虚构服务范围",
        "deadline": "2030-12-31T17:00:00+08:00", "facts": {}}), 201)["item"]


def gen(client, project, template_key, payload):
    return ok(client.post(f"/api/projects/{project['id']}/gendocs",
                          json={"template_key": template_key, "payload": payload}), 201)


# ─────────────────────────── 测试用例 ───────────────────────────


def test_checklist_templates_meta(client):
    """声明模板带 bool 字段，资质清单模板带 columns（含 bool 勾选列）。"""
    by_key = {i["key"]: i for i in ok(client.get("/api/gendocs/templates"))["items"]}
    nb = by_key["no-bribery-declaration"]
    assert nb["form_type"] == "letter"
    assert any(f["type"] == "bool" for f in nb["fields"]), "声明应含勾选项(bool字段)"
    qc = by_key["qualification-checklist"]
    assert qc["form_type"] == "table"
    assert qc.get("columns"), "资质清单应下发 columns 元数据"
    assert any(c["key"] == "provided" and c["type"] == "bool" for c in qc["columns"])
    # 计算列不下发给前端（此处无计算列，确保 columns 至少含首列 name）
    assert qc["columns"][0]["key"] == "name"


def test_no_bribery_declaration_generates(client):
    """无行贿声明：勾选/未勾选符号并存，投标人替换，不残留占位符。"""
    p = new_project(client)
    result = gen(client, p, "no-bribery-declaration", {
        "bidder_name": "诚信建设集团", "no_major_violation": False, "sign_date": "2026年10月1日"})
    raw = client.get(result["file"]["download_url"]).content
    assert hashlib.sha256(raw).hexdigest() == result["file"]["sha256"]
    text = "\n".join(par.text for par in Document(io.BytesIO(raw)).paragraphs)
    assert CHECKED in text and UNCHECKED in text, "应同时出现 ☑ 与 □"
    assert "诚信建设集团" in text
    assert "无行贿犯罪记录" in text
    assert "{{" not in text and "}}" not in text


def test_qualification_checklist_generates(client):
    """资质清单：☑/□ 勾选列、select 值映射为中文、行数与竖向页面。"""
    p = new_project(client)
    result = gen(client, p, "qualification-checklist", {"rows": [
        {"name": "营业执照", "provided": True, "copies": 2, "doc_form": "copy"},
        {"name": "工程监理资质证书", "provided": False, "doc_form": "original", "remark": "办理中"},
    ]})
    raw = client.get(result["file"]["download_url"]).content
    doc = Document(io.BytesIO(raw))
    assert doc.sections[0].page_width < doc.sections[0].page_height, "应为竖向A4"
    table = doc.tables[0]
    assert len(table.rows) == 3, "1 表头 + 2 数据"
    assert [c.text for c in table.rows[0].cells] == ["序号", "资质 / 证明文件名称", "是否提供", "份数", "原件/复印件", "备注"]
    all_text = " ".join(c.text for r in table.rows for c in r.cells)
    assert CHECKED in all_text and UNCHECKED in all_text
    assert "复印件" in all_text and "原件" in all_text, "select 应映射为中文标签"
    assert "营业执照" in all_text


def test_checklist_rejects_bad_input(client):
    """未知字段 422；资质清单空 rows 422。"""
    p = new_project(client)
    resp = client.post(f"/api/projects/{p['id']}/gendocs", json={
        "template_key": "no-bribery-declaration",
        "payload": {"bidder_name": "X", "not_a_field": "Y"}})
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"

    empty_rows = client.post(f"/api/projects/{p['id']}/gendocs", json={
        "template_key": "qualification-checklist", "payload": {"rows": []}})
    assert empty_rows.status_code == 422


def test_checklist_does_not_invalidate_review(client):
    """生成勾选类附件不应改变项目版本或复核状态。"""
    p = new_project(client)
    before = ok(client.get(f"/api/projects/{p['id']}"))["item"]
    gen(client, p, "qualification-checklist", {"rows": [{"name": "营业执照", "doc_form": "copy"}]})
    gen(client, p, "no-bribery-declaration", {"bidder_name": "某公司"})
    after = ok(client.get(f"/api/projects/{p['id']}"))["item"]
    assert after["version"] == before["version"]
    assert after["review_status"] == before["review_status"]
