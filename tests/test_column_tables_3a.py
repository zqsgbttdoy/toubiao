"""列式复用表格（P2 批次 3A）生成器测试。

监理工作制度清单 / 监理实施细则清单 / IDI平台上传责任分工表 / 拟投入主要材料计划表——
覆盖注册与列元数据下发、业务类型隔离（监理特有 / TIS 特有 / 通用）、select 值→标签映射、
横向 A4 与打印溢出保护，以及输入校验与「生成不失效复核」回归护栏。独立文件自带 fixture。
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

P3A_KEYS = {"supervision-systems", "supervision-rules", "idi-upload-duty", "material-plan"}


@pytest.fixture
def settings(tmp_path):
    return Settings(tmp_path / "isolated_data_columns_3a", parse_timeout=20)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings), base_url=ORIGIN, headers={"Origin": ORIGIN}) as session:
        yield session


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def new_project(client, business="supervision"):
    return ok(client.post("/api/projects", json={
        "name": "【虚构测试】3A列式项目", "business_type": business,
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


def test_3a_all_registered_and_columns(client):
    """4 表全部注册，form_type=table 且下发采集列。"""
    by_key = {i["key"]: i for i in ok(client.get("/api/gendocs/templates"))["items"]}
    for key in P3A_KEYS:
        assert key in by_key, key
        assert by_key[key]["form_type"] == "table", key
        assert by_key[key]["columns"], f"{key} 应下发列元数据"


def test_3a_business_isolation(client):
    """制度/细则清单仅监理；IDI分工表仅 TIS；材料计划表两类通用。"""
    sup = {i["key"] for i in ok(client.get("/api/gendocs/templates?business_type=supervision"))["items"]}
    tis = {i["key"] for i in ok(client.get("/api/gendocs/templates?business_type=tis"))["items"]}
    assert "supervision-systems" in sup and "supervision-systems" not in tis
    assert "supervision-rules" in sup and "supervision-rules" not in tis
    assert "idi-upload-duty" in tis and "idi-upload-duty" not in sup
    assert "material-plan" in sup and "material-plan" in tis


def test_supervision_system_select_mapping(client):
    """工作制度清单：category select 值渲染为中文标签，表头与行数据落位。"""
    p = new_project(client)
    body = table_body(doc_of(client, gen(client, p, "supervision-systems", {"rows": [
        {"category": "safety", "name": "监理例会制度", "content": "每周组织例会并形成纪要",
         "scope": "全体监理人员", "records": "会议纪要台账"}]})))
    assert "安全生产" in body, "category=safety 应映射为『安全生产』"
    assert "制度类别" in body and "监理例会制度" in body and "会议纪要台账" in body


def test_idi_duty_select_mapping_portrait(client):
    """IDI分工表：竖向 A4；duty=check 映射『审核确认』。"""
    p = new_project(client, "tis")
    doc = doc_of(client, gen(client, p, "idi-upload-duty", {"rows": [
        {"node": "检查结果上传", "content": "必检节点检测报告", "duty": "check",
         "owner": "项目总监", "deadline": "24小时"}]}))
    assert not is_landscape(doc), "IDI分工表应为竖向A4"
    body = table_body(doc)
    assert "审核确认" in body and "检查结果上传" in body and "24小时" in body


def test_3a_landscape_tables(client):
    """实施细则清单与材料计划表为横向 A4，行数据落位。"""
    p = new_project(client)
    rules = doc_of(client, gen(client, p, "supervision-rules", {"rows": [
        {"area": "混凝土结构", "rule_name": "旁站实施细则", "method": "旁站",
         "control_points": "浇筑前隐蔽验收"}]}))
    assert is_landscape(rules)
    body = table_body(rules)
    assert "专业/部位" in body and "混凝土结构" in body and "隐蔽验收" in body

    mp = doc_of(client, gen(client, p, "material-plan", {"rows": [
        {"name": "商品混凝土", "spec": "C30", "unit": "m³", "quantity": 1200,
         "period": "第一批次", "quality": "GB/T 14902"}]}))
    assert is_landscape(mp)
    mp_body = table_body(mp)
    assert "商品混凝土" in mp_body and "1200" in mp_body and "GB/T 14902" in mp_body


def test_3a_wide_tables_fit_printable_width(client):
    """横向表（细则/材料）tblGrid 列宽合计不超 A4 横向可用宽度（含 1 列容差）。"""
    p = new_project(client)
    usable_twips = int((29.7 - 3.0) * 567)
    for key, row in (
        ("supervision-rules", {"area": "部位"}),
        ("material-plan", {"name": "材料"}),
    ):
        doc = doc_of(client, gen(client, p, key, {"rows": [row]}))
        grid = doc.tables[0]._tbl.find(qn("w:tblGrid"))
        total = sum(int(gc.get(qn("w:w"))) for gc in grid.findall(qn("w:gridCol")))
        assert total <= usable_twips + 567, f"{key} 列宽 {total/567:.2f}cm 溢出"


def test_3a_validation_and_review_guard(client):
    """空 rows 422；未知字段 422；生成不改变版本与复核状态；sha256 一致。"""
    p = new_project(client)
    before = ok(client.get(f"/api/projects/{p['id']}"))["item"]

    assert client.post(f"/api/projects/{p['id']}/gendocs", json={
        "template_key": "supervision-systems", "payload": {"rows": []}}).status_code == 422

    assert client.post(f"/api/projects/{p['id']}/gendocs", json={
        "template_key": "supervision-systems",
        "payload": {"rows": [{"name": "例会制度", "bogus": "x"}]}}).status_code == 422

    result = gen(client, p, "supervision-systems", {"rows": [{"category": "quality", "name": "平行检验制度"}]})
    raw = client.get(result["file"]["download_url"]).content
    assert hashlib.sha256(raw).hexdigest() == result["file"]["sha256"]
    after = ok(client.get(f"/api/projects/{p['id']}"))["item"]
    assert after["version"] == before["version"]
    assert after["review_status"] == before["review_status"]
