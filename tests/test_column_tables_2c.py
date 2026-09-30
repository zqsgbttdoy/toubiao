"""列式复用表格（P1 批次 2C）生成器测试。

办公设施表 / TIS检测设备表 / 旁站方案 / 见证取样 / 风险分级标准 / 报告时效 / 财务证明——
覆盖列元数据下发、select 值→标签映射、金额千分位、横向 A4 溢出保护、业务类型隔离，
以及输入校验与「生成不失效复核」回归护栏。独立文件自带 fixture。
"""
import hashlib
import io
import pytest
from fastapi.testclient import TestClient
from docx import Document
from docx.oxml.ns import qn

from app.core import Settings
from app.main import create_app

ORIGIN = "http://127.0.0.1:8000"

C2C_KEYS = {"office-facilities", "tis-detection-equipment", "witness-plan", "sampling-plan",
            "risk-grade-standard", "report-timeliness", "finance-proof"}


@pytest.fixture
def settings(tmp_path):
    return Settings(tmp_path / "isolated_data_columns_2c", parse_timeout=20)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings), base_url=ORIGIN, headers={"Origin": ORIGIN}) as session:
        yield session


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def new_project(client, business="supervision"):
    return ok(client.post("/api/projects", json={
        "name": "【虚构测试】2C列式项目", "business_type": business,
        "region": "示例地区", "client": "虚构委托单位", "scope": "虚构服务范围",
        "deadline": "2030-12-31T17:00:00+08:00", "facts": {}}), 201)["item"]


def gen(client, project, template_key, payload):
    return ok(client.post(f"/api/projects/{project['id']}/gendocs",
                          json={"template_key": template_key, "payload": payload}), 201)


def doc_of(client, result):
    return Document(io.BytesIO(client.get(result["file"]["download_url"]).content))


def table_body(doc):
    return " ".join(c.text for t in doc.tables for r in t.rows for c in r.cells)


def is_landscape(doc):
    s = doc.sections[0]
    return s.page_width > s.page_height


# ─────────────────────────── 测试用例 ───────────────────────────


def test_2c_all_registered_and_columns(client):
    """7 表全部注册，form_type=table 且下发采集列（无计算列）。"""
    by_key = {i["key"]: i for i in ok(client.get("/api/gendocs/templates"))["items"]}
    for key in C2C_KEYS:
        assert key in by_key, key
        assert by_key[key]["form_type"] == "table", key
        assert by_key[key]["columns"], f"{key} 应下发列元数据"


def test_2c_business_isolation(client):
    """TIS检测设备表仅 TIS；旁站/见证取样仅监理；其余两类通用。"""
    sup = {i["key"] for i in ok(client.get("/api/gendocs/templates?business_type=supervision"))["items"]}
    tis = {i["key"] for i in ok(client.get("/api/gendocs/templates?business_type=tis"))["items"]}
    assert "tis-detection-equipment" in tis and "tis-detection-equipment" not in sup
    assert "witness-plan" in sup and "witness-plan" not in tis
    assert "sampling-plan" in sup and "sampling-plan" not in tis
    for key in ("office-facilities", "risk-grade-standard", "report-timeliness", "finance-proof"):
        assert key in sup and key in tis


def test_office_facilities_select_mapping_and_landscape(client):
    """办公设施表：横向 A4 + 类别 select 值渲染为中文标签。"""
    p = new_project(client)
    result = gen(client, p, "office-facilities", {"rows": [
        {"name": "笔记本电脑", "category": "office", "quantity": 5, "unit": "台", "purpose": "现场办公"}]})
    doc = doc_of(client, result)
    assert is_landscape(doc), "办公设施表应横向A4"
    body = table_body(doc)
    assert "办公设备" in body, "category=office 应映射为『办公设备』"
    assert "笔记本电脑" in body and "现场办公" in body


def test_finance_money_thousand_separator(client):
    """财务证明：金额列千分位 + 两位小数；表头带单位。"""
    p = new_project(client)
    result = gen(client, p, "finance-proof", {"rows": [
        {"year": "2023", "revenue": "1234567.5", "net_profit": "200000",
         "total_assets": "5000000", "liability": "1000000", "auditor": "某会计师事务所"}]})
    doc = doc_of(client, result)
    body = table_body(doc)
    assert "1,234,567.50" in body, "营业收入应千分位格式化"
    assert "营业收入(元)" in body and "某会计师事务所" in body


def test_risk_grade_and_report_headers(client):
    """风险分级标准表与报告时效表：关键表头存在，行数据落位。"""
    p = new_project(client)
    rg = table_body(doc_of(client, gen(client, p, "risk-grade-standard", {"rows": [
        {"level": "严重", "criteria": "可能导致群死群伤", "control": "公司级管控"}]})))
    assert "分级判定标准" in rg and "严重" in rg and "公司级管控" in rg

    rt = table_body(doc_of(client, gen(client, p, "report-timeliness", {"rows": [
        {"report_type": "不合格报告", "deadline": "12小时", "recipient": "建设单位"}]})))
    assert "报告类别" in rt and "提交时限" in rt and "不合格报告" in rt and "12小时" in rt


def test_wide_landscape_tables_fit_printable_width(client):
    """横向表（办公设施/财务证明）的 tblGrid 列宽合计不超 A4 横向可用宽度。"""
    p = new_project(client)
    usable_twips = int((29.7 - 3.0) * 567)
    for key, row in (
        ("office-facilities", {"name": "设备"}),
        ("finance-proof", {"year": "2023"}),
        ("tis-detection-equipment", {"name": "内窥镜"}),
    ):
        proj = new_project(client, "tis") if key == "tis-detection-equipment" else p
        doc = doc_of(client, gen(client, proj, key, {"rows": [row]}))
        grid = doc.tables[0]._tbl.find(qn("w:tblGrid"))
        total = sum(int(gc.get(qn("w:w"))) for gc in grid.findall(qn("w:gridCol")))
        assert total <= usable_twips + 567, f"{key} 列宽 {total/567:.2f}cm 溢出"


def test_2c_validation_and_review_guard(client):
    """空 rows 422；未知字段 422；生成不改变版本与复核状态。"""
    p = new_project(client)
    before = ok(client.get(f"/api/projects/{p['id']}"))["item"]

    assert client.post(f"/api/projects/{p['id']}/gendocs", json={
        "template_key": "witness-plan", "payload": {"rows": []}}).status_code == 422

    assert client.post(f"/api/projects/{p['id']}/gendocs", json={
        "template_key": "witness-plan",
        "payload": {"rows": [{"process": "浇筑", "bogus": "x"}]}}).status_code == 422

    result = gen(client, p, "witness-plan", {"rows": [{"process": "混凝土浇筑", "location": "基础底板"}]})
    raw = client.get(result["file"]["download_url"]).content
    assert hashlib.sha256(raw).hexdigest() == result["file"]["sha256"]
    after = ok(client.get(f"/api/projects/{p['id']}"))["item"]
    assert after["version"] == before["version"]
    assert after["review_status"] == before["review_status"]
