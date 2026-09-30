"""内部复核表（P1 批次 2F）生成器测试。

复用列式引擎渲染「复核项目 × 结论」主体，末尾追加复核结论行 + 编制/复核/审核批准三签栏。
覆盖：列元数据下发、result select 值→标签映射（精确单元格匹配避免子串误判）、竖向 A4、
序号列、三签签署栏（提供姓名显姓名 / 留空显占位）、业务通用性，以及输入校验与
「生成不失效复核」回归护栏。独立文件自带 fixture。
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
    return Settings(tmp_path / "isolated_data_review_2f", parse_timeout=20)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings), base_url=ORIGIN, headers={"Origin": ORIGIN}) as session:
        yield session


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def new_project(client, business="supervision"):
    return ok(client.post("/api/projects", json={
        "name": "【虚构测试】2F内部复核项目", "business_type": business,
        "region": "示例地区", "client": "虚构委托单位", "scope": "虚构服务范围",
        "deadline": "2030-12-31T17:00:00+08:00", "facts": {}}), 201)["item"]


def gen(client, project, template_key, payload):
    return ok(client.post(f"/api/projects/{project['id']}/gendocs",
                          json={"template_key": template_key, "payload": payload}), 201)


def doc_of(client, result):
    return Document(io.BytesIO(client.get(result["file"]["download_url"]).content))


def cell_texts(doc):
    """所有单元格文本（去空白）集合，用于精确匹配避免子串误判。"""
    return {c.text.strip() for t in doc.tables for r in t.rows for c in r.cells}


def all_text(doc):
    return " ".join(c.text for t in doc.tables for r in t.rows for c in r.cells)


def is_portrait(doc):
    s = doc.sections[0]
    return s.page_width < s.page_height


# ─────────────────────────── 测试用例 ───────────────────────────


def test_review_registered_and_columns(client):
    """internal-review 注册为 form_type=table，下发 item/standard/result/remark 列，
    result 为 select 且候选含『符合』。"""
    by_key = {i["key"]: i for i in ok(client.get("/api/gendocs/templates"))["items"]}
    assert "internal-review" in by_key
    tpl = by_key["internal-review"]
    assert tpl["form_type"] == "table"
    keys = [c["key"] for c in tpl["columns"]]
    assert keys == ["item", "standard", "result", "remark"], keys
    result_col = next(c for c in tpl["columns"] if c["key"] == "result")
    assert result_col["type"] == "select"
    assert "符合" in result_col["options"].values()


def test_review_business_available_for_both(client):
    """内部复核表监理与 TIS 均可用（质量记录通用）。"""
    sup = {i["key"] for i in ok(client.get("/api/gendocs/templates?business_type=supervision"))["items"]}
    tis = {i["key"] for i in ok(client.get("/api/gendocs/templates?business_type=tis"))["items"]}
    assert "internal-review" in sup and "internal-review" in tis


def test_review_body_select_mapping_and_portrait(client):
    """竖向 A4 + 含序号共 5 列；result 值渲染为中文标签（精确单元格匹配）。"""
    p = new_project(client)
    result = gen(client, p, "internal-review", {"rows": [
        {"item": "资质文件完整性", "standard": "营业执照/资质证书齐全", "result": "fit", "remark": ""},
        {"item": "报价一致性", "standard": "大写与小写金额一致", "result": "unfit", "remark": "核实后修正"},
        {"item": "签章齐全", "result": "na"}]})
    doc = doc_of(client, result)
    assert is_portrait(doc), "内部复核表应为竖向A4"
    assert len(doc.tables[0].columns) == 5, "序号 + 4 数据列 = 5"

    cells = cell_texts(doc)
    assert "符合" in cells and "不符合" in cells and "不适用" in cells, "select 应映射为中文标签"
    assert "资质文件完整性" in cells and "核实后修正" in cells


def test_review_footer_and_three_signatures(client):
    """末尾含复核结论行 + 编制/复核/审核批准三签；提供姓名显姓名，留空显占位下划线。"""
    p = new_project(client)
    result = gen(client, p, "internal-review", {
        "rows": [{"item": "格式复核", "result": "fit"}],
        "preparer": "张三", "reviewer": "李四"})
    body = all_text(doc_of(client, result))
    assert "复核结论" in body and "□ 通过" in body and "修改后通过" in body and "不通过" in body
    assert "编制（签署）：张三" in body
    assert "复核（签署）：李四" in body
    assert "审核／批准（签署）：" in body
    assert "＿＿＿＿＿＿＿＿＿＿" in body, "未填签署人应显示占位下划线"


def test_review_validation_and_guard(client):
    """空 rows 422；未知字段 422；生成不改变版本与复核状态；sha256 一致。"""
    p = new_project(client)
    before = ok(client.get(f"/api/projects/{p['id']}"))["item"]

    assert client.post(f"/api/projects/{p['id']}/gendocs", json={
        "template_key": "internal-review", "payload": {"rows": []}}).status_code == 422

    assert client.post(f"/api/projects/{p['id']}/gendocs", json={
        "template_key": "internal-review",
        "payload": {"rows": [{"item": "格式复核", "bogus": "x"}]}}).status_code == 422

    result = gen(client, p, "internal-review", {"rows": [{"item": "格式复核", "result": "fit"}]})
    raw = client.get(result["file"]["download_url"]).content
    assert hashlib.sha256(raw).hexdigest() == result["file"]["sha256"]
    after = ok(client.get(f"/api/projects/{p['id']}"))["item"]
    assert after["version"] == before["version"]
    assert after["review_status"] == before["review_status"]
