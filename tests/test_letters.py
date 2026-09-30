"""段落类附件（P0 批次 1A）生成器测试。

独立文件自带 fixture（无 conftest.py，跨文件导入夹具不稳），只覆盖新增的
「文本段落类」附件：投标函 / 各类证明书 / 承诺 / 委托书。
"""
import hashlib
import io
import pytest
from fastapi.testclient import TestClient
from docx import Document

from app.core import Settings
from app.main import create_app

ORIGIN = "http://127.0.0.1:8000"

LETTER_KEYS = {
    "bid-letter", "legal-rep-id", "authorization-letter",
    "chief-supervisor-appointment", "tis-independence", "credit-commitment",
}


@pytest.fixture
def settings(tmp_path):
    return Settings(tmp_path / "isolated_data_letters", parse_timeout=20)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings), base_url=ORIGIN, headers={"Origin": ORIGIN}) as session:
        yield session


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def new_project(client, business="supervision"):
    return ok(client.post("/api/projects", json={
        "name": "【虚构测试】段落附件项目", "business_type": business,
        "region": "示例地区", "client": "虚构委托单位", "scope": "虚构服务范围",
        "deadline": "2030-12-31T17:00:00+08:00", "facts": {}}), 201)["item"]


# ─────────────────────────── 测试用例 ───────────────────────────


def test_letter_templates_registered_with_fields(client):
    """模板列表应含 6 个段落类附件，form_type=letter 且暴露派生字段。"""
    items = ok(client.get("/api/gendocs/templates"))["items"]
    by_key = {i["key"]: i for i in items}
    assert LETTER_KEYS.issubset(by_key.keys())
    for key in LETTER_KEYS:
        tpl = by_key[key]
        assert tpl["form_type"] == "letter", f"{key} 应为 letter 表单"
        assert tpl["fields"], f"{key} 应暴露表单字段"
        assert all(f["label"] for f in tpl["fields"]), "每个字段都要有中文标签"
    # 表格类模板不应带 fields
    assert by_key["equipment-list"]["form_type"] == "table"
    assert "fields" not in by_key["equipment-list"] or not by_key["equipment-list"]["fields"]


def test_bid_letter_substitutes_placeholders(client):
    """投标函：占位符替换为提交值，招标人留空时回退为项目委托方。"""
    p = new_project(client)
    payload = {"bidder_name": "某监理咨询有限公司", "bid_price": "壹佰贰拾万元整",
               "duration": "365 日历天", "sign_date": "2026年10月1日"}
    result = ok(client.post(f"/api/projects/{p['id']}/gendocs",
                            json={"template_key": "bid-letter", "payload": payload}), 201)
    info = result["file"]
    raw = client.get(info["download_url"]).content
    assert hashlib.sha256(raw).hexdigest() == info["sha256"]

    text = "\n".join(par.text for par in Document(io.BytesIO(raw)).paragraphs)
    assert "投 标 函" in text                      # 主标题
    assert "某监理咨询有限公司" in text             # 投标人
    assert "壹佰贰拾万元整" in text                 # 报价占位符已替换
    assert "365 日历天" in text                     # 服务期限已替换
    assert "虚构委托单位" in text                   # 招标人回退为项目委托方
    assert "{{" not in text and "}}" not in text    # 不残留未替换标记


def test_letter_empty_payload_renders_blanks(client):
    """仅填投标人，其余留空：应正常生成且不残留 {{}}（空值渲染为填空位）。"""
    p = new_project(client)
    result = ok(client.post(f"/api/projects/{p['id']}/gendocs",
                            json={"template_key": "credit-commitment",
                                  "payload": {"bidder_name": "诚信建设集团"}}), 201)
    raw = client.get(result["file"]["download_url"]).content
    doc = Document(io.BytesIO(raw))
    text = "\n".join(par.text for par in doc.paragraphs)
    assert "诚信建设集团" in text
    assert "{{" not in text and "}}" not in text
    assert len(doc.tables) == 0, "段落类附件不应包含表格"


def test_letter_business_type_filtering(client):
    """总监任命书仅监理类、TIS 独立性承诺仅 TIS 类。"""
    sup = {i["key"] for i in ok(client.get("/api/gendocs/templates?business_type=supervision"))["items"]}
    tis = {i["key"] for i in ok(client.get("/api/gendocs/templates?business_type=tis"))["items"]}
    assert "chief-supervisor-appointment" in sup
    assert "chief-supervisor-appointment" not in tis
    assert "tis-independence" in tis
    assert "tis-independence" not in sup
    # 通用类两者都有
    assert "bid-letter" in sup and "bid-letter" in tis


def test_letter_rejects_unknown_field(client):
    """extra=forbid：提交契约外字段应被拒（422）。"""
    p = new_project(client)
    resp = client.post(f"/api/projects/{p['id']}/gendocs",
                       json={"template_key": "bid-letter",
                             "payload": {"bidder_name": "X", "not_a_field": "Y"}})
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"


def test_letter_generation_does_not_invalidate_review(client):
    """生成段落附件不应改变项目版本或复核状态。"""
    p = new_project(client)
    before = ok(client.get(f"/api/projects/{p['id']}"))["item"]
    ok(client.post(f"/api/projects/{p['id']}/gendocs",
                   json={"template_key": "legal-rep-id",
                         "payload": {"bidder_name": "某公司", "rep_name": "张代表",
                                     "rep_id_no": "11010119900101001X"}}), 201)
    after = ok(client.get(f"/api/projects/{p['id']}"))["item"]
    assert after["version"] == before["version"]
    assert after["review_status"] == before["review_status"]
