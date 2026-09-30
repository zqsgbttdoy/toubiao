"""柱状图引擎（P1 批次 2B）生成器测试。

人月计划表 / 人力投入直方图——重点覆盖 bar_kit 的「按自然月在场」统计：
每月在场人数合计（含退场留空＝至期末的开放行）、堆叠柱状的档位行数、
在场蓝色底纹、横向 A4，以及输入校验与「生成不失效复核」回归护栏。
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
PRESENT_FILL = "4F81BD"

# 期望月度在场：1月=1(张)  2月=2(张+李)  3月=2(张+王·无退场至期末)  峰值=2
ROWS = [
    {"name": "张三", "role": "总监", "entry_date": "2026-01-05", "exit_date": "2026-03-10"},
    {"name": "李四", "role": "专监", "entry_date": "2026-02-01", "exit_date": "2026-02-28"},
    {"name": "王五", "role": "监理员", "entry_date": "2026-03-01"},
]


@pytest.fixture
def settings(tmp_path):
    return Settings(tmp_path / "isolated_data_bar", parse_timeout=20)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings), base_url=ORIGIN, headers={"Origin": ORIGIN}) as session:
        yield session


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def new_project(client, business="supervision", deadline="2026-03-31T17:00:00+08:00"):
    return ok(client.post("/api/projects", json={
        "name": "【虚构测试】柱状图项目", "business_type": business,
        "region": "示例地区", "client": "虚构委托单位", "scope": "虚构服务范围",
        "deadline": deadline, "facts": {}}), 201)["item"]


def gen(client, project, template_key, payload):
    return ok(client.post(f"/api/projects/{project['id']}/gendocs",
                          json={"template_key": template_key, "payload": payload}), 201)


def doc_of(client, result):
    return Document(io.BytesIO(client.get(result["file"]["download_url"]).content))


def shade_fills(doc):
    fills = set()
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                tc_pr = cell._tc.find(qn("w:tcPr"))
                if tc_pr is None:
                    continue
                for node in tc_pr.findall(qn("w:shd")):
                    fills.add(node.get(qn("w:fill")))
    return fills


# ─────────────────────────── 测试用例 ───────────────────────────


def test_bar_templates_form_type_and_columns(client):
    """两张柱状图 form_type=bar，下发采集列（无 time_scale、无计算列）。"""
    by_key = {i["key"]: i for i in ok(client.get("/api/gendocs/templates"))["items"]}
    for key in ("manpower-plan", "manpower-histogram"):
        tpl = by_key[key]
        assert tpl["form_type"] == "bar", key
        assert {c["key"] for c in tpl["columns"]} == {"name", "role", "entry_date", "exit_date"}, key


def test_manpower_plan_monthly_counts(client):
    """人月计划表：横向 A4 + 在场蓝色底纹 + 末行每月在场人数 1/2/2 + sha256 稳定。"""
    p = new_project(client)
    result = gen(client, p, "manpower-plan", {"rows": ROWS})
    raw = client.get(result["file"]["download_url"]).content
    assert hashlib.sha256(raw).hexdigest() == result["file"]["sha256"]
    doc = Document(io.BytesIO(raw))
    assert doc.sections[0].page_width > doc.sections[0].page_height, "应为横向A4"
    assert PRESENT_FILL in shade_fills(doc), "在场月份应涂蓝色"
    last = [c.text for c in doc.tables[0].rows[-1].cells]
    assert last[:2] == ["合计", "每月在场人数"]
    assert last[-3:] == ["1", "2", "2"], f"每月在场人数应为 1/2/2，实得 {last[-3:]}"


def test_manpower_histogram_levels_and_counts(client):
    """人力投入直方图：档位行数=峰值(2)+月份标签行+合计行=4，合计行 1/2/2。"""
    p = new_project(client)
    result = gen(client, p, "manpower-histogram", {"rows": ROWS})
    doc = doc_of(client, result)
    table = doc.tables[0]
    assert len(table.rows) == 4, "峰值2 → 2档位行 + 标签行 + 合计行"
    assert len(table.columns) == 4, "1 人数轴 + 3 个自然月"
    counts = [c.text for c in table.rows[-1].cells]
    assert counts[0] == "当月合计" and counts[1:] == ["1", "2", "2"]
    assert PRESENT_FILL in shade_fills(doc)


def test_bar_available_for_both_business(client):
    """人月计划/直方图对监理类与 TIS 类均开放。"""
    sup = {i["key"] for i in ok(client.get("/api/gendocs/templates?business_type=supervision"))["items"]}
    tis = {i["key"] for i in ok(client.get("/api/gendocs/templates?business_type=tis"))["items"]}
    for key in ("manpower-plan", "manpower-histogram"):
        assert key in sup and key in tis


def test_bar_validation_and_review_guard(client):
    """进场晚于退场 422；空 rows 422；未知字段 422；生成不改变版本与复核状态。"""
    p = new_project(client)
    before = ok(client.get(f"/api/projects/{p['id']}"))["item"]

    assert client.post(f"/api/projects/{p['id']}/gendocs", json={
        "template_key": "manpower-plan",
        "payload": {"rows": [{"name": "甲", "role": "总监", "entry_date": "2026-03-01", "exit_date": "2026-02-01"}]}
    }).status_code == 422, "进场晚于退场应拒绝"

    assert client.post(f"/api/projects/{p['id']}/gendocs", json={
        "template_key": "manpower-plan", "payload": {"rows": []}}).status_code == 422

    assert client.post(f"/api/projects/{p['id']}/gendocs", json={
        "template_key": "manpower-plan",
        "payload": {"rows": [{"name": "甲", "role": "总监", "entry_date": "2026-01-01", "bogus": "x"}]}
    }).status_code == 422, "未知字段应拒绝"

    gen(client, p, "manpower-plan", {"rows": ROWS})
    after = ok(client.get(f"/api/projects/{p['id']}"))["item"]
    assert after["version"] == before["version"]
    assert after["review_status"] == before["review_status"]
