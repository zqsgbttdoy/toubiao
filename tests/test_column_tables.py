"""列式扩展表格（P0 批次 1C）生成器测试。

覆盖横向多列、计算列（在场天数 / 小计）、合计行、金额千分位、select 映射，
以及输入校验与「生成不失效复核」回归护栏。独立文件自带 fixture。
"""
import hashlib
import io
import pytest
from decimal import Decimal
from fastapi.testclient import TestClient
from docx import Document
from docx.oxml.ns import qn

from app.core import Settings
from app.main import create_app

ORIGIN = "http://127.0.0.1:8000"


@pytest.fixture
def settings(tmp_path):
    return Settings(tmp_path / "isolated_data_columns", parse_timeout=20)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings), base_url=ORIGIN, headers={"Origin": ORIGIN}) as session:
        yield session


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def new_project(client, business="supervision"):
    return ok(client.post("/api/projects", json={
        "name": "【虚构测试】列式表格项目", "business_type": business,
        "region": "示例地区", "client": "虚构委托单位", "scope": "虚构服务范围",
        "deadline": "2030-12-31T17:00:00+08:00", "facts": {}}), 201)["item"]


def gen(client, project, template_key, payload):
    return ok(client.post(f"/api/projects/{project['id']}/gendocs",
                          json={"template_key": template_key, "payload": payload}), 201)


def doc_of(client, result):
    raw = client.get(result["file"]["download_url"]).content
    return Document(io.BytesIO(raw))


# ─────────────────────────── 测试用例 ───────────────────────────


def test_column_templates_expose_columns_without_computed(client):
    """横向表下发 columns，且计算列（on_site_days / subtotal）不进入前端字段。"""
    by_key = {i["key"]: i for i in ok(client.get("/api/gendocs/templates"))["items"]}
    sr = by_key["staff-register"]["columns"]
    assert all(c["key"] != "on_site_days" for c in sr), "计算列不应下发前端"
    assert any(c["key"] == "entry_date" and c["type"] == "date" for c in sr)
    qd = by_key["quotation-detail"]["columns"]
    assert all(c["key"] != "subtotal" for c in qd)
    assert any(c["key"] == "unit_price" for c in qd)


def test_staff_register_landscape_and_computed_days(client):
    """进退场登记表：横向页面 + 在场天数按进退场自动计算 + 状态映射。"""
    p = new_project(client)
    result = gen(client, p, "staff-register", {"rows": [{
        "name": "张三", "role": "总监", "entry_date": "2026-01-01",
        "exit_date": "2026-01-31", "work_status": "on_site"}]})
    raw = client.get(result["file"]["download_url"]).content
    assert hashlib.sha256(raw).hexdigest() == result["file"]["sha256"]
    doc = Document(io.BytesIO(raw))
    assert doc.sections[0].page_width > doc.sections[0].page_height, "应为横向A4"
    header = [c.text for c in doc.tables[0].rows[0].cells]
    row = [c.text for c in doc.tables[0].rows[1].cells]
    assert "在场天数" in header
    assert row[header.index("在场天数")] == "31", "2026-01-01 至 01-31 应为 31 天"
    assert "在场" in " ".join(row)


def test_quotation_detail_subtotal_and_total(client):
    """报价明细：逐行小计 = 数量×单价，末行合计汇总。"""
    p = new_project(client)
    result = gen(client, p, "quotation-detail", {"rows": [
        {"name": "监理费", "unit": "人月", "quantity": "3", "unit_price": "10000"},
        {"name": "检测费", "unit": "次", "quantity": "5", "unit_price": "2000"},
    ]})
    table = doc_of(client, result).tables[0]
    body = " ".join(c.text for r in table.rows for c in r.cells)
    assert "30,000.00" in body and "10,000.00" in body, "小计/单价应千分位格式化"
    assert "合计" in body
    assert "40,000.00" in body, "合计 = 30000 + 10000 = 40000"


def test_bid_openning_money_format(client):
    """开标一览表：投标总价按千分位 + 两位小数展示。"""
    p = new_project(client)
    result = gen(client, p, "bid-opening", {"rows": [
        {"section": "一标段", "total_price": "1234567.5"}]})
    body = " ".join(c.text for r in doc_of(client, result).tables[0].rows for c in r.cells)
    assert "1,234,567.50" in body
    assert "一标段" in body


def test_org_composition_supervision_only(client):
    """机构组成表仅监理类可用。"""
    sup = {i["key"] for i in ok(client.get("/api/gendocs/templates?business_type=supervision"))["items"]}
    tis = {i["key"] for i in ok(client.get("/api/gendocs/templates?business_type=tis"))["items"]}
    assert "org-composition" in sup
    assert "org-composition" not in tis


def test_landscape_tables_fit_printable_width(client):
    """横向多列表（16/19 列）的 tblGrid 实际列宽不得超出 A4 横向可用宽度（报告溢出风险的缓解）。"""
    p = new_project(client)
    # A4 横向可用宽 = 29.7cm - 左右边距 1.5*2 = 26.7cm；twips → cm 除以 567。
    usable_twips = int((29.7 - 3.0) * 567)
    for key, row in (
        ("staff-register", {"name": "张三", "role": "总监"}),
        ("similar-projects", {"name": "某监理项目"}),
    ):
        result = gen(client, p, key, {"rows": [row]})
        doc = doc_of(client, result)
        grid = doc.tables[0]._tbl.find(qn("w:tblGrid"))
        total_twips = sum(int(gc.get(qn("w:w"))) for gc in grid.findall(qn("w:gridCol")))
        assert total_twips <= usable_twips + 567, f"{key} 列宽合计 {total_twips/567:.2f}cm 溢出"


def test_column_tables_validation_and_review_guard(client):
    """空 rows 422；未知字段 422；生成不改变版本与复核状态。"""
    p = new_project(client)
    before = ok(client.get(f"/api/projects/{p['id']}"))["item"]

    assert client.post(f"/api/projects/{p['id']}/gendocs", json={
        "template_key": "staff-certificate", "payload": {"rows": []}}).status_code == 422

    assert client.post(f"/api/projects/{p['id']}/gendocs", json={
        "template_key": "staff-certificate",
        "payload": {"rows": [{"name": "李四", "bogus": "x"}]}}).status_code == 422

    gen(client, p, "staff-certificate", {"rows": [{"name": "李四", "role": "专监", "cert_no": "J2026001"}]})
    after = ok(client.get(f"/api/projects/{p['id']}"))["item"]
    assert after["version"] == before["version"]
    assert after["review_status"] == before["review_status"]
