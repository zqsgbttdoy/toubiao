"""列式复用表格（P0 批次 1D）生成器测试。

商务 / 技术偏离表、风险识别清单、TIS 检查节点计划表、TIS 团队配置表——
重点覆盖 select 值→标签映射（偏离情况 / 风险等级）、TIS 专属业务过滤、
number 列渲染，以及输入校验与「生成不失效复核」回归护栏。独立文件自带 fixture。
"""
import hashlib
import io
import pytest
from fastapi.testclient import TestClient
from docx import Document

from app.core import Settings
from app.main import create_app

ORIGIN = "http://127.0.0.1:8000"

ONE_D_KEYS = {
    "commercial-deviation", "technical-deviation", "risk-register",
    "tis-inspection-nodes", "tis-team-config",
}


@pytest.fixture
def settings(tmp_path):
    return Settings(tmp_path / "isolated_data_columns_1d", parse_timeout=20)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings), base_url=ORIGIN, headers={"Origin": ORIGIN}) as session:
        yield session


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def new_project(client, business="supervision"):
    return ok(client.post("/api/projects", json={
        "name": "【虚构测试】列式复用项目", "business_type": business,
        "region": "示例地区", "client": "虚构委托单位", "scope": "虚构服务范围",
        "deadline": "2030-12-31T17:00:00+08:00", "facts": {}}), 201)["item"]


def gen(client, project, template_key, payload):
    return ok(client.post(f"/api/projects/{project['id']}/gendocs",
                          json={"template_key": template_key, "payload": payload}), 201)


def doc_of(client, result):
    raw = client.get(result["file"]["download_url"]).content
    return Document(io.BytesIO(raw))


def table_body(client, result):
    return " ".join(c.text for r in doc_of(client, result).tables[0].rows for c in r.cells)


# ─────────────────────────── 测试用例 ───────────────────────────


def test_one_d_templates_registered_with_columns(client):
    """5 个 1D 表模板全部下发，且带列元数据、排除计算列（无）。"""
    by_key = {i["key"]: i for i in ok(client.get("/api/gendocs/templates"))["items"]}
    assert ONE_D_KEYS <= set(by_key), "1D 模板应全部注册"
    cd = by_key["commercial-deviation"]["columns"]
    assert {c["key"] for c in cd} == {"clause", "clause_name", "bid_response", "deviation", "remark"}
    assert any(c["key"] == "deviation" and c["type"] == "select" for c in cd)


def test_commercial_deviation_select_mapping(client):
    """商务偏离表：deviation 值渲染为中文标签，无偏离/正/负偏离均可识别。"""
    p = new_project(client)
    result = gen(client, p, "commercial-deviation", {"rows": [
        {"clause": "3.1", "clause_name": "工期", "bid_response": "完全响应", "deviation": "none"},
        {"clause": "3.2", "clause_name": "付款", "bid_response": "可协商", "deviation": "negative",
         "remark": "建议调整"}]})
    raw = client.get(result["file"]["download_url"]).content
    assert hashlib.sha256(raw).hexdigest() == result["file"]["sha256"]
    body = table_body(client, result)
    assert "无偏离" in body and "负偏离" in body, "select 应映射为中文标签"
    assert "3.1" in body and "建议调整" in body


def test_technical_deviation_and_risk_level_mapping(client):
    """技术偏离表 + 风险清单：风险等级 select 映射为极高/高/中/低。"""
    p = new_project(client)
    tech = gen(client, p, "technical-deviation", {"rows": [
        {"clause": "抗震等级", "tender_requirement": "8度", "bid_response": "满足", "deviation": "positive"}]})
    assert "正偏离" in table_body(client, tech)

    risk = gen(client, p, "risk-register", {"rows": [
        {"category": "高处作业", "location": "外立面", "description": "坠落风险",
         "level": "high", "consequence": "人员伤亡", "measure": "安全网+持证", "responsible": "李四/3日"}]})
    risk_body = table_body(client, risk)
    assert "高" in risk_body and "安全网+持证" in risk_body


def test_tis_templates_only_for_tis_business(client):
    """TIS 检查节点 / 团队配置表仅 tis 类可用，监理类不可见。"""
    sup = {i["key"] for i in ok(client.get("/api/gendocs/templates?business_type=supervision"))["items"]}
    tis = {i["key"] for i in ok(client.get("/api/gendocs/templates?business_type=tis"))["items"]}
    assert "tis-inspection-nodes" in tis and "tis-team-config" in tis
    assert "tis-inspection-nodes" not in sup and "tis-team-config" not in sup


def test_tis_team_config_number_column(client):
    """TIS 团队配置表：从业年限 number 列原样渲染，整数不带小数。"""
    p = new_project(client, business="tis")
    result = gen(client, p, "tis-team-config", {"rows": [
        {"role": "项目经理", "name": "王五", "title_level": "高工", "qualification": "注册监理",
         "experience_years": 12, "major": "房建", "onsite_plan": "全职"}]})
    body = table_body(client, result)
    assert "12" in body and "项目经理" in body and "注册监理" in body


def test_one_d_validation_and_review_guard(client):
    """空 rows 422；未知字段 422；非法枚举 422；生成不改变版本与复核状态。"""
    p = new_project(client)
    before = ok(client.get(f"/api/projects/{p['id']}"))["item"]

    assert client.post(f"/api/projects/{p['id']}/gendocs", json={
        "template_key": "risk-register", "payload": {"rows": []}}).status_code == 422

    assert client.post(f"/api/projects/{p['id']}/gendocs", json={
        "template_key": "commercial-deviation",
        "payload": {"rows": [{"clause": "2.1", "bogus": "x"}]}}).status_code == 422

    assert client.post(f"/api/projects/{p['id']}/gendocs", json={
        "template_key": "commercial-deviation",
        "payload": {"rows": [{"clause": "2.1", "deviation": "不存在的值"}]}}).status_code == 422

    gen(client, p, "commercial-deviation", {"rows": [{"clause": "2.1", "deviation": "none"}]})
    after = ok(client.get(f"/api/projects/{p['id']}"))["item"]
    assert after["version"] == before["version"]
    assert after["review_status"] == before["review_status"]
