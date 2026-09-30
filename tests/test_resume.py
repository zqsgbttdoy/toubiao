"""履历版式（P1 批次 2D）生成器测试。

监理人员简历表——覆盖 resume_kit 的竖向表单版式：form_type=resume、采集列元数据、
每人一张表、跨列字段合并、主要经历多段分行、从业年限数字渲染，
以及输入校验（空 rows / 未知字段 / 年限越界）与「生成不失效复核」回归护栏。
独立文件自带 fixture。
"""
import hashlib
import io
import pytest
from fastapi.testclient import TestClient
from docx import Document

from app.core import Settings
from app.main import create_app

ORIGIN = "http://127.0.0.1:8000"
KEY = "supervisor-resume"


@pytest.fixture
def settings(tmp_path):
    return Settings(tmp_path / "isolated_data_resume", parse_timeout=20)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings), base_url=ORIGIN, headers={"Origin": ORIGIN}) as session:
        yield session


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def new_project(client, business="supervision"):
    return ok(client.post("/api/projects", json={
        "name": "【虚构测试】简历表项目", "business_type": business,
        "region": "示例地区", "client": "虚构委托单位", "scope": "虚构服务范围",
        "deadline": "2030-12-31T17:00:00+08:00", "facts": {}}), 201)["item"]


def gen(client, project, payload):
    return ok(client.post(f"/api/projects/{project['id']}/gendocs",
                          json={"template_key": KEY, "payload": payload}), 201)


def doc_of(client, result):
    return Document(io.BytesIO(client.get(result["file"]["download_url"]).content))


PERSON = {
    "name": "张三", "gender": "男", "age": "45", "title_level": "高级工程师",
    "qualification": "注册监理工程师（编号 2026001）", "education": "本科",
    "major": "土木工程", "years": 20, "project_role": "总监理工程师",
    "certs": "监理工程师证书", "experience": "2015-2018 A项目 总监\n2018-2022 B项目 专监",
}


# ─────────────────────────── 测试用例 ───────────────────────────


def test_resume_form_type_and_columns(client):
    """form_type=resume，下发采集列（含全部字段与 experience）。"""
    tpl = {i["key"]: i for i in ok(client.get("/api/gendocs/templates"))["items"]}[KEY]
    assert tpl["form_type"] == "resume"
    keys = {c["key"] for c in tpl["columns"]}
    assert {"name", "qualification", "years", "certs", "experience"} <= keys
    assert any(c["key"] == "name" and c["required"] for c in tpl["columns"])


def test_resume_renders_person_form(client):
    """竖向 A4 + 每人一张四列表 + 跨列资格值 + 多行经历 + 年限数字 + sha256 稳定。"""
    p = new_project(client)
    result = gen(client, p, {"rows": [PERSON]})
    raw = client.get(result["file"]["download_url"]).content
    assert hashlib.sha256(raw).hexdigest() == result["file"]["sha256"]
    doc = Document(io.BytesIO(raw))
    assert doc.sections[0].page_width < doc.sections[0].page_height, "简历表应为竖向A4"
    table = doc.tables[0]
    assert len(table.columns) == 4, "四列（标签·值·标签·值）"
    body = " ".join(c.text for r in table.rows for c in r.cells)
    assert "注册监理工程师（编号 2026001）" in body, "跨列字段值应完整渲染"
    assert "主要监理经历" in body and "2018-2022 B项目 专监" in body
    assert "20" in body, "从业年限数字应落位"


def test_resume_multiple_people_one_table_each(client):
    """多人各渲染一张独立表（分页）。"""
    p = new_project(client)
    result = gen(client, p, {"rows": [PERSON, {"name": "李四", "title_level": "工程师", "years": 8}]})
    doc = doc_of(client, result)
    assert len(doc.tables) == 2, "每人一张表"
    names = [para.text for para in doc.paragraphs if para.text.startswith("2.")]
    assert names and "李四" in names[0]


def test_resume_available_for_both_business(client):
    sup = {i["key"] for i in ok(client.get("/api/gendocs/templates?business_type=supervision"))["items"]}
    tis = {i["key"] for i in ok(client.get("/api/gendocs/templates?business_type=tis"))["items"]}
    assert KEY in sup and KEY in tis


def test_resume_validation_and_review_guard(client):
    """空 rows 422；未知字段 422；年限越界 422；生成不改变版本与复核状态。"""
    p = new_project(client)
    before = ok(client.get(f"/api/projects/{p['id']}"))["item"]

    assert client.post(f"/api/projects/{p['id']}/gendocs", json={
        "template_key": KEY, "payload": {"rows": []}}).status_code == 422

    assert client.post(f"/api/projects/{p['id']}/gendocs", json={
        "template_key": KEY,
        "payload": {"rows": [{"name": "王五", "bogus": "x"}]}}).status_code == 422

    assert client.post(f"/api/projects/{p['id']}/gendocs", json={
        "template_key": KEY,
        "payload": {"rows": [{"name": "王五", "years": 200}]}}).status_code == 422, "从业年限应 ≤60"

    gen(client, p, {"rows": [PERSON]})
    after = ok(client.get(f"/api/projects/{p['id']}"))["item"]
    assert after["version"] == before["version"]
    assert after["review_status"] == before["review_status"]
