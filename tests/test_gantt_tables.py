"""横道图复用（P1 批次 2A）生成器测试。

施工进度横道图 / TIS 检查节点横道图——重点覆盖 gantt_kit 复用基类的
form_type=gantt 与列元数据下发、字段标签映射、蓝/灰横道底纹、横向 A4、
显式时间刻度的确定性地列数，以及输入校验与「生成不失效复核」回归护栏。
独立文件自带 fixture（无 conftest.py，跨文件导入夹具不稳）。
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
BAR_CONFIRMED = "4F81BD"
BAR_OPEN = "BFBFBF"

GANTT_KEYS = {"personnel-gantt", "schedule-gantt", "tis-inspection-gantt"}


@pytest.fixture
def settings(tmp_path):
    return Settings(tmp_path / "isolated_data_gantt", parse_timeout=20)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings), base_url=ORIGIN, headers={"Origin": ORIGIN}) as session:
        yield session


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def new_project(client, business="supervision", deadline="2030-12-31T17:00:00+08:00"):
    return ok(client.post("/api/projects", json={
        "name": "【虚构测试】横道图复用项目", "business_type": business,
        "region": "示例地区", "client": "虚构委托单位", "scope": "虚构服务范围",
        "deadline": deadline, "facts": {}}), 201)["item"]


def gen(client, project, template_key, payload):
    return ok(client.post(f"/api/projects/{project['id']}/gendocs",
                          json={"template_key": template_key, "payload": payload}), 201)


def raw_of(client, result):
    return client.get(result["file"]["download_url"]).content


def doc_of(client, result):
    return Document(io.BytesIO(raw_of(client, result)))


def shade_fills(doc):
    fills = set()
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                shd = cell._tc.find(qn("w:tcPr"))
                if shd is None:
                    continue
                for node in shd.findall(qn("w:shd")):
                    fills.add(node.get(qn("w:fill")))
    return fills


# ─────────────────────────── 测试用例 ───────────────────────────


def test_gantt_templates_form_type_and_columns(client):
    """三张横道图 form_type=gantt，并按 gantt_kit 列元数据下发采集字段（无计算列）。"""
    by_key = {i["key"]: i for i in ok(client.get("/api/gendocs/templates"))["items"]}
    for key in GANTT_KEYS:
        tpl = by_key[key]
        assert tpl["form_type"] == "gantt", key
        col_keys = {c["key"] for c in tpl["columns"]}
        assert {"name", "role", "entry_date", "exit_date", "note"} <= col_keys, key
        assert all(c["type"] != "computed" for c in tpl["columns"])


def test_schedule_gantt_uses_configured_labels(client):
    """施工进度横道图：横向 A4 + 子类配置的字段标签 + 蓝色横道底纹 + sha256 稳定。"""
    p = new_project(client)
    result = gen(client, p, "schedule-gantt", {"rows": [
        {"name": "土方开挖", "role": "地基基础", "entry_date": "2026-01-05", "exit_date": "2026-02-10"},
    ]})
    raw = raw_of(client, result)
    assert hashlib.sha256(raw).hexdigest() == result["file"]["sha256"]
    doc = Document(io.BytesIO(raw))
    assert doc.sections[0].page_width > doc.sections[0].page_height, "横道图应为横向A4"
    header = " ".join(c.text for r in doc.tables[0].rows[:2] for c in r.cells)
    assert "工序名称" in header and "所属分部" in header, "应采用子类配置的列标签"
    body = " ".join(c.text for r in doc.tables[0].rows for c in r.cells)
    assert "土方开挖" in body and "地基基础" in body
    assert BAR_CONFIRMED in shade_fills(doc), "已确定结束的工序应绘制蓝色横道"


def test_tis_inspection_gantt_tis_only(client):
    """TIS 检查横道图仅 TIS 类可用；施工进度横道图两类通用。"""
    sup = {i["key"] for i in ok(client.get("/api/gendocs/templates?business_type=supervision"))["items"]}
    tis = {i["key"] for i in ok(client.get("/api/gendocs/templates?business_type=tis"))["items"]}
    assert "schedule-gantt" in sup and "schedule-gantt" in tis
    assert "tis-inspection-gantt" in tis
    assert "tis-inspection-gantt" not in sup


def test_open_bar_gray_and_endless_label(client):
    """结束日期留空 → 灰色横道 + 结束列显示「持续至期末」。"""
    p = new_project(client, deadline="2026-06-30T17:00:00+08:00")
    result = gen(client, p, "schedule-gantt", {"rows": [
        {"name": "收尾整改", "role": "装饰装修", "entry_date": "2026-05-01"},
    ]})
    doc = doc_of(client, result)
    body = " ".join(c.text for r in doc.tables[0].rows for c in r.cells)
    assert "持续至期末" in body
    fills = shade_fills(doc)
    assert BAR_OPEN in fills and BAR_CONFIRMED not in fills, "开放式时段仅灰色横道"


def test_explicit_month_scale_deterministic_columns(client):
    """显式 month 刻度：时间列数 = 覆盖月份数，不受自动升档影响（守跨档位断言陷阱）。"""
    p = new_project(client, deadline="2026-03-20T17:00:00+08:00")
    result = gen(client, p, "schedule-gantt", {
        "time_scale": "month",
        "rows": [
            {"name": "甲工序", "role": "基础", "entry_date": "2026-01-05", "exit_date": "2026-02-10"},
            {"name": "乙工序", "role": "主体", "entry_date": "2026-02-11", "exit_date": "2026-03-15"},
        ]})
    doc = doc_of(client, result)
    grid = doc.tables[0]._tbl.find(qn("w:tblGrid"))
    grid_cols = len(grid.findall(qn("w:gridCol")))
    # 2026-01-05 至 2026-03-20 跨 3 个自然月：5 信息列 + 3 时间列 + 1 备注列 = 9。
    assert grid_cols == 9, f"month 刻度应得 3 个时间列，实际 gridCol={grid_cols}"


def test_gantt_validation_and_review_guard(client):
    """进场晚于出场 422；空 rows 422；未知字段 422；生成不改变版本与复核状态。"""
    p = new_project(client)
    before = ok(client.get(f"/api/projects/{p['id']}"))["item"]

    assert client.post(f"/api/projects/{p['id']}/gendocs", json={
        "template_key": "schedule-gantt",
        "payload": {"rows": [{"name": "甲", "role": "基础", "entry_date": "2026-03-01", "exit_date": "2026-02-01"}]}
    }).status_code == 422, "进场晚于出场应拒绝"

    assert client.post(f"/api/projects/{p['id']}/gendocs", json={
        "template_key": "schedule-gantt", "payload": {"rows": []}}).status_code == 422

    assert client.post(f"/api/projects/{p['id']}/gendocs", json={
        "template_key": "schedule-gantt",
        "payload": {"rows": [{"name": "甲", "role": "基础", "entry_date": "2026-01-01", "bogus": "x"}]}
    }).status_code == 422, "未知字段应拒绝"

    gen(client, p, "schedule-gantt", {"rows": [
        {"name": "甲", "role": "基础", "entry_date": "2026-01-01", "exit_date": "2026-01-20"}]})
    after = ok(client.get(f"/api/projects/{p['id']}"))["item"]
    assert after["version"] == before["version"]
    assert after["review_status"] == before["review_status"]
