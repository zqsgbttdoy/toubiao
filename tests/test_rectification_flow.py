"""整改闭环流程表（P2 批次 3B）生成器测试。

层级图引擎新增 FlowBuilder 流程形态：按「上一环节编号」串联顺序、蛇形多行排布、
框首「→」示意推进。覆盖注册与列元数据（流程表头）、监理四步单行 / TIS 六步换行排布、
箭头连接示意、横向 A4 溢出保护、业务通用性，以及输入校验与「生成不失效复核」回归护栏。
独立文件自带 fixture。
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


@pytest.fixture
def settings(tmp_path):
    return Settings(tmp_path / "isolated_data_flow_3b", parse_timeout=20)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings), base_url=ORIGIN, headers={"Origin": ORIGIN}) as session:
        yield session


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def new_project(client, business="supervision"):
    return ok(client.post("/api/projects", json={
        "name": "【虚构测试】3B整改流程项目", "business_type": business,
        "region": "示例地区", "client": "虚构委托单位", "scope": "虚构服务范围",
        "deadline": "2030-12-31T17:00:00+08:00", "facts": {}}), 201)["item"]


def gen(client, project, payload):
    return ok(client.post(f"/api/projects/{project['id']}/gendocs",
                          json={"template_key": "rectification-flow", "payload": payload}), 201)


def doc_of(client, result):
    return Document(io.BytesIO(client.get(result["file"]["download_url"]).content))


def chain(n):
    """构造 n 环节顺序链：1 ← 2 ← … ← n（parent=上一环节编号）。"""
    names = ["签发整改通知单", "实施整改", "复查验证", "闭合归档", "整改方案审核", "拒不上报时报建设方"]
    return [{"id": str(i + 1), "label": names[i % len(names)], "person": f"岗位{i + 1}",
             "parent": "" if i == 0 else str(i)} for i in range(n)]


# ─────────────────────────── 测试用例 ───────────────────────────


def test_flow_registered_with_flow_headers(client):
    """注册为 form_type=hierarchy，列头切换为流程语义（环节编号/上一环节编号）。"""
    tpl = {i["key"]: i for i in ok(client.get("/api/gendocs/templates"))["items"]}["rectification-flow"]
    assert tpl["form_type"] == "hierarchy"
    cols = {c["key"]: c["label"] for c in tpl["columns"]}
    assert set(cols) == {"id", "label", "person", "parent"}
    assert cols["label"] == "环节名称" and cols["parent"] == "上一环节编号"


def test_flow_available_for_both_business(client):
    """监理与 TIS 均可用（整改闭环两类业务都需要，步骤差异仅在文案指引）。"""
    sup = {i["key"] for i in ok(client.get("/api/gendocs/templates?business_type=supervision"))["items"]}
    tis = {i["key"] for i in ok(client.get("/api/gendocs/templates?business_type=tis"))["items"]}
    assert "rectification-flow" in sup and "rectification-flow" in tis


def test_flow_four_steps_single_row_with_arrows(client):
    """监理惯用四步：一行 4 框；除首框外框首均有「→」，首框无箭头；责任人落位。"""
    p = new_project(client)
    doc = doc_of(client, gen(client, p, {"rows": chain(4)}))
    table = doc.tables[0]
    assert doc.sections[0].page_width > doc.sections[0].page_height, "流程表应横向A4"
    assert len(table.rows) == 1 and len(table.columns) == 4
    cells = [c.text.strip() for c in table.rows[0].cells]
    assert cells[0] == "签发整改通知单\n岗位1", f"首框不应有箭头：{cells[0]!r}"
    assert all(c.startswith("→ ") for c in cells[1:]), "后续框行首应有推进箭头"
    body = " ".join(cells)
    assert "实施整改" in body and "复查验证" in body and "闭合归档" in body


def test_flow_six_steps_wraps(client):
    """TIS 惯用六步：每行最多 5 框 → 2 行，表格宽度按 5 列均分。"""
    p = new_project(client, "tis")
    doc = doc_of(client, gen(client, p, {"rows": chain(6)}))
    table = doc.tables[0]
    assert len(table.rows) == 2 and len(table.columns) == 5
    first_row = [c.text.strip() for c in table.rows[0].cells if c.text.strip()]
    assert len(first_row) == 5, "第一行应排满 5 个环节框"
    # 第二行仅 1 框：占满整行→合并单元格在 row.cells 中重复引用同一格，按去重集合判断
    second_row = {c.text.strip() for c in table.rows[1].cells if c.text.strip()}
    assert len(second_row) == 1 and next(iter(second_row)).startswith("→ ")


def test_flow_legend_and_wide_fit(client):
    """正文含闭环图例（监理四步/TIS六步指引）；tblGrid 列宽合计不超横向可用宽度。"""
    p = new_project(client)
    doc = doc_of(client, gen(client, p, {"rows": chain(6)}))
    text = "\n".join(par.text for par in doc.paragraphs)
    assert "整改通知单→实施整改→复查→闭合" in text, "图例应含监理四步惯用链"
    assert "拒不上报" in text, "图例应含 TIS 拒不上报机制提示"
    usable_twips = int((29.7 - 3.0) * 567)
    grid = doc.tables[0]._tbl.find(qn("w:tblGrid"))
    total = sum(int(gc.get(qn("w:w"))) for gc in grid.findall(qn("w:gridCol")))
    assert total <= usable_twips + 567, f"列宽 {total/567:.2f}cm 溢出"


def test_flow_validation_and_review_guard(client):
    """空 rows 422；未知字段 422；生成不改变版本与复核状态；sha256 一致。"""
    p = new_project(client)
    before = ok(client.get(f"/api/projects/{p['id']}"))["item"]

    assert client.post(f"/api/projects/{p['id']}/gendocs", json={
        "template_key": "rectification-flow", "payload": {"rows": []}}).status_code == 422

    assert client.post(f"/api/projects/{p['id']}/gendocs", json={
        "template_key": "rectification-flow",
        "payload": {"rows": [{"id": "1", "label": "通知", "bogus": "x"}]}}).status_code == 422

    result = gen(client, p, {"rows": chain(4)})
    raw = client.get(result["file"]["download_url"]).content
    assert hashlib.sha256(raw).hexdigest() == result["file"]["sha256"]
    after = ok(client.get(f"/api/projects/{p['id']}"))["item"]
    assert after["version"] == before["version"]
    assert after["review_status"] == before["review_status"]
