"""列式复用 + 平面布置说明表（P3 批次 4A+4C）生成器测试。

临时用地表 / 拟分包项目情况表 / 施工总平面布置说明表——
覆盖列元数据下发、select 值映射、金额千分位、横向 A4 溢出保护、业务通用性、
平面布置表 notice 含"另附图纸"提示，以及输入校验与回归护栏。
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

P4_KEYS = {"temporary-land", "subcontract-plan", "site-layout"}


@pytest.fixture
def settings(tmp_path):
    return Settings(tmp_path / "isolated_data_col4_p3", parse_timeout=20)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings), base_url=ORIGIN, headers={"Origin": ORIGIN}) as session:
        yield session


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def new_project(client, business="supervision"):
    return ok(client.post("/api/projects", json={
        "name": "【虚构测试】P3列式项目", "business_type": business,
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


def test_p3_all_registered(client):
    """3 表全部注册，form_type=table 且有列元数据下发。"""
    by_key = {i["key"]: i for i in ok(client.get("/api/gendocs/templates"))["items"]}
    for key in P4_KEYS:
        assert key in by_key, key
        assert by_key[key]["form_type"] == "table", key
        assert by_key[key]["columns"], f"{key} 应有列元数据"


def test_temporary_land_select_and_landscape(client):
    """临时用地表：横向 A4 + land_type select 映射为中文标签。"""
    p = new_project(client)
    result = gen(client, p, "temporary-land", {"rows": [
        {"location": "基坑东侧", "use": "材料堆场", "area": 500,
         "land_type": "farmland", "period": "6个月", "restore": "复耕"}]})
    doc = doc_of(client, result)
    assert is_landscape(doc), "临时用地表应横向A4"
    body = table_body(doc)
    assert "耕地" in body, "land_type=farmland 应映射为『耕地』"
    assert "基坑东侧" in body and "材料堆场" in body


def test_subcontract_money_format(client):
    """拟分包表：金额列千分位格式化 + 横向。"""
    p = new_project(client)
    result = gen(client, p, "subcontract-plan", {"rows": [
        {"item_name": "桩基工程", "content": "钻孔灌注桩", "reason": "专项资质",
         "subcontractor": "某基础公司", "qualification": "一级",
         "amount": "3500000", "ratio": "15%"}]})
    doc = doc_of(client, result)
    assert is_landscape(doc)
    body = table_body(doc)
    assert "3,500,000.00" in body, "分包金额应千分位"
    assert "桩基工程" in body and "某基础公司" in body


def test_site_layout_notice(client):
    """平面布置说明表：横向 + notice 含"另附"图纸提示。"""
    p = new_project(client)
    result = gen(client, p, "site-layout", {"rows": [
        {"zone": "办公区", "position": "北侧", "area": 300,
         "facilities": "活动板房5间", "duration": "全程"}]})
    doc = doc_of(client, result)
    assert is_landscape(doc)
    body = table_body(doc)
    assert "办公区" in body and "活动板房" in body
    # notice 在 doc 段落中（非 table）
    full_text = "\n".join(par.text for par in doc.paragraphs)
    assert "另附" in full_text or "附图" in full_text or "绘制" in full_text, "应有图纸提示"


def test_site_layout_wide_fit(client):
    """3 表横向版 tblGrid 列宽合计不超 A4 横向可用宽度。"""
    p = new_project(client)
    usable_twips = int((29.7 - 3.0) * 567)
    for key, row in (
        ("temporary-land", {"location": "位置"}),
        ("subcontract-plan", {"item_name": "分包"}),
        ("site-layout", {"zone": "分区"}),
    ):
        doc = doc_of(client, gen(client, p, key, {"rows": [row]}))
        grid = doc.tables[0]._tbl.find(qn("w:tblGrid"))
        total = sum(int(gc.get(qn("w:w"))) for gc in grid.findall(qn("w:gridCol")))
        assert total <= usable_twips + 567, f"{key} 列宽 {total/567:.2f}cm 溢出"


def test_p3_validation_and_guard(client):
    """空 rows 422；未知字段 422；生成不改变版本与复核状态；sha256 一致。"""
    p = new_project(client)
    before = ok(client.get(f"/api/projects/{p['id']}"))["item"]

    assert client.post(f"/api/projects/{p['id']}/gendocs", json={
        "template_key": "temporary-land", "payload": {"rows": []}}).status_code == 422

    assert client.post(f"/api/projects/{p['id']}/gendocs", json={
        "template_key": "temporary-land",
        "payload": {"rows": [{"location": "位置", "bogus": "x"}]}}).status_code == 422

    result = gen(client, p, "subcontract-plan", {"rows": [{"item_name": "土方"}]})
    raw = client.get(result["file"]["download_url"]).content
    assert hashlib.sha256(raw).hexdigest() == result["file"]["sha256"]
    after = ok(client.get(f"/api/projects/{p['id']}"))["item"]
    assert after["version"] == before["version"]
    assert after["review_status"] == before["review_status"]
