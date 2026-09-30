"""层级图引擎（P1 批次 2E）生成器测试。

机构层级图 / TIS 团队层级图——覆盖 hierarchy_kit 的按 parent 分层、合框居中、
连接线（子框顶「│」、根框无连线）、缺失父级按根处理、横向 A4，
以及业务类型隔离、输入校验与「生成不失效复核」回归护栏。独立文件自带 fixture。
"""
import hashlib
import io
import pytest
from fastapi.testclient import TestClient
from docx import Document

from app.core import Settings
from app.main import create_app

ORIGIN = "http://127.0.0.1:8000"

TREE = [
    {"id": "1", "label": "总监理工程师", "person": "张三"},
    {"id": "2", "label": "专监A", "person": "李四", "parent": "1"},
    {"id": "3", "label": "专监B", "person": "王五", "parent": "1"},
    {"id": "4", "label": "监理员", "person": "赵六", "parent": "2"},
]


@pytest.fixture
def settings(tmp_path):
    return Settings(tmp_path / "isolated_data_hierarchy", parse_timeout=20)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings), base_url=ORIGIN, headers={"Origin": ORIGIN}) as session:
        yield session


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def new_project(client, business="supervision"):
    return ok(client.post("/api/projects", json={
        "name": "【虚构测试】层级图项目", "business_type": business,
        "region": "示例地区", "client": "虚构委托单位", "scope": "虚构服务范围",
        "deadline": "2030-12-31T17:00:00+08:00", "facts": {}}), 201)["item"]


def gen(client, project, template_key, payload):
    return ok(client.post(f"/api/projects/{project['id']}/gendocs",
                          json={"template_key": template_key, "payload": payload}), 201)


def doc_of(client, result):
    return Document(io.BytesIO(client.get(result["file"]["download_url"]).content))


def table_body(doc):
    return " ".join(c.text for t in doc.tables for r in t.rows for c in r.cells)


# ─────────────────────────── 测试用例 ───────────────────────────


def test_hierarchy_form_type_and_columns(client):
    by_key = {i["key"]: i for i in ok(client.get("/api/gendocs/templates"))["items"]}
    for key in ("org-hierarchy", "tis-team-hierarchy"):
        assert by_key[key]["form_type"] == "hierarchy", key
        assert {c["key"] for c in by_key[key]["columns"]} == {"id", "label", "person", "parent"}, key


def test_hierarchy_business_isolation(client):
    sup = {i["key"] for i in ok(client.get("/api/gendocs/templates?business_type=supervision"))["items"]}
    tis = {i["key"] for i in ok(client.get("/api/gendocs/templates?business_type=tis"))["items"]}
    assert "org-hierarchy" in sup and "org-hierarchy" not in tis
    assert "tis-team-hierarchy" in tis and "tis-team-hierarchy" not in sup


def test_org_hierarchy_tiers_and_connectors(client):
    """四层节点归并为 3 个层级行、最宽层 2 列；子框有「│」连线，横向 A4。"""
    p = new_project(client)
    result = gen(client, p, "org-hierarchy", {"rows": TREE})
    raw = client.get(result["file"]["download_url"]).content
    assert hashlib.sha256(raw).hexdigest() == result["file"]["sha256"]
    doc = Document(io.BytesIO(raw))
    assert doc.sections[0].page_width > doc.sections[0].page_height, "层级图应横向A4"
    table = doc.tables[0]
    assert len(table.rows) == 3, "总监/专监/监理员 共 3 层"
    assert len(table.columns) == 2, "最宽层 2 个节点 → 2 列"
    body = table_body(doc)
    assert all(x in body for x in ("总监理工程师", "专监A", "专监B", "监理员"))
    assert "│" in body, "子节点框顶应有连接线"


def test_root_only_has_no_connector(client):
    """仅根节点（无 parent）时不绘制连接线；父级缺失亦按根处理。"""
    p = new_project(client)
    result = gen(client, p, "org-hierarchy", {"rows": [
        {"id": "1", "label": "总监"}, {"id": "2", "label": "专监", "parent": "99"}]})
    body = table_body(doc_of(client, result))
    assert "总监" in body and "专监" in body
    assert "│" not in body, "两个都是根节点，不应出现连接线"


def test_hierarchy_validation_and_review_guard(client):
    """空 rows 422；未知字段 422；生成不改变版本与复核状态。"""
    p = new_project(client)
    before = ok(client.get(f"/api/projects/{p['id']}"))["item"]

    assert client.post(f"/api/projects/{p['id']}/gendocs", json={
        "template_key": "org-hierarchy", "payload": {"rows": []}}).status_code == 422

    assert client.post(f"/api/projects/{p['id']}/gendocs", json={
        "template_key": "org-hierarchy",
        "payload": {"rows": [{"id": "1", "label": "总监", "bogus": "x"}]}}).status_code == 422

    gen(client, p, "org-hierarchy", {"rows": TREE})
    after = ok(client.get(f"/api/projects/{p['id']}"))["item"]
    assert after["version"] == before["version"]
    assert after["review_status"] == before["review_status"]
