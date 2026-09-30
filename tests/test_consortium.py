"""联合体协议书（P3 批次 4B）生成器测试。

复用段落引擎 LetterBuilder，仅重写 build() 渲染「牵头人 + 逐家成员单位」多方签署栏。
覆盖：form_type=letter 与字段表单派生、正文占位符替换、按 member_units 分隔数量动态
生成签署块（填 2 家成员→牵头人+2 成员=3 个盖章块、各带法代签字行）、空成员只签牵头人、
业务通用性，以及未知字段校验与「生成不失效复核」回归护栏。
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
    return Settings(tmp_path / "isolated_data_consortium_p3", parse_timeout=20)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings), base_url=ORIGIN, headers={"Origin": ORIGIN}) as session:
        yield session


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def new_project(client, business="supervision"):
    return ok(client.post("/api/projects", json={
        "name": "【虚构测试】P3联合体项目", "business_type": business,
        "region": "示例地区", "client": "虚构委托单位", "scope": "虚构服务范围",
        "deadline": "2030-12-31T17:00:00+08:00", "facts": {}}), 201)["item"]


def gen(client, project, payload):
    return ok(client.post(f"/api/projects/{project['id']}/gendocs",
                          json={"template_key": "consortium-agreement", "payload": payload}), 201)


def doc_of(client, result):
    return Document(io.BytesIO(client.get(result["file"]["download_url"]).content))


def para_texts(doc):
    return [p.text for p in doc.paragraphs]


# ─────────────────────────── 测试用例 ───────────────────────────


def test_consortium_registered_as_letter(client):
    """注册为 form_type=letter，字段表单由 payload_model 派生（含牵头/成员/分工等）。"""
    tpl = {i["key"]: i for i in ok(client.get("/api/gendocs/templates"))["items"]}["consortium-agreement"]
    assert tpl["form_type"] == "letter"
    field_keys = {f["key"] for f in tpl["fields"]}
    assert {"lead_unit", "member_units", "work_division", "profit_ratio"} <= field_keys


def test_consortium_body_placeholders(client):
    """正文占位符替换：牵头人/成员/分工/连带责任渲染到段落。"""
    p = new_project(client)
    doc = doc_of(client, gen(client, p, {
        "lead_unit": "甲监理公司", "member_units": "乙咨询公司",
        "work_division": "甲方负责现场，乙方负责内业", "profit_ratio": "按 6:4 分配"}))
    text = "\n".join(para_texts(doc))
    assert "联合体协议书" in text
    assert "甲监理公司" in text and "乙咨询公司" in text
    assert "甲方负责现场" in text and "连带责任" in text


def test_consortium_multi_sign_blocks(client):
    """填 2 家成员单位 → 牵头人 + 2 成员 = 3 个盖章块，各配一行法代签字。"""
    p = new_project(client)
    doc = doc_of(client, gen(client, p, {
        "lead_unit": "牵头A", "member_units": "成员B、成员C"}))
    texts = para_texts(doc)
    seal_lines = [t for t in texts if "（盖章）：" in t]
    sign_lines = [t for t in texts if "法定代表人或其委托代理人（签字）" in t]
    assert len(seal_lines) == 3, f"应 3 个盖章块，实得 {seal_lines}"
    assert len(sign_lines) == 3, "每个签署块各一行法代签字"
    joined = "\n".join(texts)
    assert "牵头人（盖章）：牵头A" in joined
    assert "成员单位（盖章）：成员B" in joined and "成员单位（盖章）：成员C" in joined


def test_consortium_only_lead_when_no_member(client):
    """无成员单位时仅牵头人一个签署块。"""
    p = new_project(client)
    doc = doc_of(client, gen(client, p, {"lead_unit": "单独牵头X"}))
    seal_lines = [t for t in para_texts(doc) if "（盖章）：" in t]
    assert len(seal_lines) == 1 and "牵头人（盖章）：单独牵头X" in seal_lines[0]


def test_consortium_business_and_guard(client):
    """监理/TIS 均可用；未知字段 422；生成不改版本与复核状态；sha256 一致。"""
    sup = {i["key"] for i in ok(client.get("/api/gendocs/templates?business_type=supervision"))["items"]}
    tis = {i["key"] for i in ok(client.get("/api/gendocs/templates?business_type=tis"))["items"]}
    assert "consortium-agreement" in sup and "consortium-agreement" in tis

    p = new_project(client)
    before = ok(client.get(f"/api/projects/{p['id']}"))["item"]
    assert client.post(f"/api/projects/{p['id']}/gendocs", json={
        "template_key": "consortium-agreement",
        "payload": {"lead_unit": "A", "bogus": "x"}}).status_code == 422

    result = gen(client, p, {"lead_unit": "A", "member_units": "B"})
    raw = client.get(result["file"]["download_url"]).content
    assert hashlib.sha256(raw).hexdigest() == result["file"]["sha256"]
    after = ok(client.get(f"/api/projects/{p['id']}"))["item"]
    assert after["version"] == before["version"]
    assert after["review_status"] == before["review_status"]
