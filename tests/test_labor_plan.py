"""劳动力配置计划表（P2 批次 3C）生成器测试。

柱状图引擎人数加权扩展（show_count）：行＝工种、每行带「计划人数」，
月度在场人数＝Σ在场工种人数（加权），网格与直方图组合输出。
覆盖列元数据含人数列、加权月度合计、双表版式、抬头汇总文案、
既有柱状图模板不泄漏 count 列（零回归），以及输入校验与复核护栏。独立文件自带 fixture。
"""
import hashlib
import io
import pytest
from fastapi.testclient import TestClient
from docx import Document
from docx.oxml.ns import qn

from app.core import Settings
from app.gendocs.bar_kit import PRESENT_FILL
from app.main import create_app

ORIGIN = "http://127.0.0.1:8000"

# 木工 8 人(1~2月)、钢筋工 12 人(1~3月)、电工 5 人(2月起至期末)
# 加权月度在场：1月 8+12=20；2月 8+12+5=25；3月 12+5=17
ROWS = [
    {"name": "木工班组", "role": "模板", "count": 8,
     "entry_date": "2026-01-05", "exit_date": "2026-02-28"},
    {"name": "钢筋工班组", "role": "结构", "count": 12,
     "entry_date": "2026-01-05", "exit_date": "2026-03-10"},
    {"name": "电工班组", "role": "安装", "count": 5, "entry_date": "2026-02-01"},
]


@pytest.fixture
def settings(tmp_path):
    return Settings(tmp_path / "isolated_data_labor_3c", parse_timeout=20)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings), base_url=ORIGIN, headers={"Origin": ORIGIN}) as session:
        yield session


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def new_project(client, business="supervision", deadline="2026-03-31T17:00:00+08:00"):
    return ok(client.post("/api/projects", json={
        "name": "【虚构测试】3C劳动力项目", "business_type": business,
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


def test_labor_registered_with_count_column(client):
    """form_type=bar，采集列在岗位后插入「计划人数」；既有柱状模板不泄漏 count 列。"""
    by_key = {i["key"]: i for i in ok(client.get("/api/gendocs/templates"))["items"]}
    tpl = by_key["labor-plan"]
    assert tpl["form_type"] == "bar"
    assert [c["key"] for c in tpl["columns"]] == ["name", "role", "count", "entry_date", "exit_date"]
    assert tpl["columns"][2]["label"] == "计划人数"
    # 零回归：人月计划/直方图仍为 4 列，不含 count
    for key in ("manpower-plan", "manpower-histogram"):
        assert {c["key"] for c in by_key[key]["columns"]} == {"name", "role", "entry_date", "exit_date"}, key


def test_labor_grid_weighted_monthly_counts(client):
    """网格末行每月在场人数按人数加权：20 / 25 / 17；在场格涂蓝；人数列落位。"""
    p = new_project(client)
    doc = doc_of(client, gen(client, p, "labor-plan", {"rows": ROWS}))
    assert doc.sections[0].page_width > doc.sections[0].page_height, "应为横向A4"
    grid = doc.tables[0]
    header = [c.text for c in grid.rows[0].cells]
    assert "计划人数" in header and "工种/班组" in header
    last = [c.text for c in grid.rows[-1].cells]
    assert last[:2] == ["合计", "每月在场人数"]
    assert last[-3:] == ["20", "25", "17"], f"加权月度人数应为 20/25/17，实得 {last[-3:]}"
    body = " ".join(c.text for r in grid.rows for c in r.cells)
    assert "木工班组" in body and "电工班组" in body
    assert PRESENT_FILL in shade_fills(doc), "在场月份应涂蓝色"


def test_labor_histogram_second_table(client):
    """组合版式：网格之后第二张表为直方图，合计行同样加权 20/25/17，档位行=峰值25。"""
    p = new_project(client)
    doc = doc_of(client, gen(client, p, "labor-plan", {"rows": ROWS}))
    assert len(doc.tables) == 2, "网格 + 直方图两张表"
    hist = doc.tables[1]
    assert len(hist.columns) == 4, "1 人数轴 + 3 个自然月"
    assert len(hist.rows) == 25 + 2, "峰值25 → 25 档位行 + 标签行 + 合计行"
    counts = [c.text for c in hist.rows[-1].cells]
    assert counts[0] == "当月合计" and counts[1:] == ["20", "25", "17"]


def test_labor_heading_summary(client):
    """抬头汇总：工种 3 类·合计 25 人；峰值人力按加权计。"""
    p = new_project(client)
    doc = doc_of(client, gen(client, p, "labor-plan", {"rows": ROWS}))
    text = "\n".join(par.text for par in doc.paragraphs)
    assert "工种 3 类·合计 25 人" in text
    assert "峰值人力 25 人·月" in text


def test_labor_business_both(client):
    """监理与 TIS 均可用。"""
    sup = {i["key"] for i in ok(client.get("/api/gendocs/templates?business_type=supervision"))["items"]}
    tis = {i["key"] for i in ok(client.get("/api/gendocs/templates?business_type=tis"))["items"]}
    assert "labor-plan" in sup and "labor-plan" in tis


def test_labor_validation_and_review_guard(client):
    """空 rows 422；count=0 越界 422；未知字段 422；生成不改变版本与复核状态；sha256 一致。"""
    p = new_project(client)
    before = ok(client.get(f"/api/projects/{p['id']}"))["item"]

    assert client.post(f"/api/projects/{p['id']}/gendocs", json={
        "template_key": "labor-plan", "payload": {"rows": []}}).status_code == 422

    bad = dict(ROWS[0], count=0)
    assert client.post(f"/api/projects/{p['id']}/gendocs", json={
        "template_key": "labor-plan", "payload": {"rows": [bad]}}).status_code == 422

    assert client.post(f"/api/projects/{p['id']}/gendocs", json={
        "template_key": "labor-plan",
        "payload": {"rows": [dict(ROWS[0], bogus="x")]}}).status_code == 422

    result = gen(client, p, "labor-plan", {"rows": ROWS})
    raw = client.get(result["file"]["download_url"]).content
    assert hashlib.sha256(raw).hexdigest() == result["file"]["sha256"]
    after = ok(client.get(f"/api/projects/{p['id']}"))["item"]
    assert after["version"] == before["version"]
    assert after["review_status"] == before["review_status"]
