"""附件文档生成模块测试。"""
import hashlib
import io
import pytest
from datetime import date, timedelta
from fastapi.testclient import TestClient
from docx import Document

from app.core import Settings
from app.main import create_app

ORIGIN = "http://127.0.0.1:8000"


@pytest.fixture
def settings(tmp_path):
    return Settings(tmp_path / "isolated_data", parse_timeout=20)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings), base_url=ORIGIN, headers={"Origin": ORIGIN}) as session:
        yield session


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def new_project(client, business="supervision"):
    return ok(client.post("/api/projects", json={
        "name": "【虚构测试】附件生成项目", "business_type": business,
        "region": "示例地区", "client": "虚构委托单位", "scope": "虚构服务范围",
        "deadline": "2030-12-31T17:00:00+08:00", "facts": {}}), 201)["item"]


# ─────────────────────────── 测试用例 ───────────────────────────


def test_gendoc_templates_listed(client):
    """GET 模板列表包含 personnel-gantt 和 equipment-list。"""
    result = ok(client.get("/api/gendocs/templates"))
    keys = [item["key"] for item in result["items"]]
    assert "personnel-gantt" in keys
    assert "equipment-list" in keys
    # 每个模板有 title 和 description
    for item in result["items"]:
        assert item["title"]
        assert item["description"]


def test_personnel_gantt_generates_valid_docx(client):
    """POST 人员数据生成横道图 docx，验证表格结构和单元格着色。"""
    p = new_project(client)
    today = date.today()
    payload = {
        "rows": [
            {"name": "张三", "role": "总监理工程师", "entry_date": str(today), "exit_date": str(today + timedelta(days=30)), "note": ""},
            {"name": "李四", "role": "专业监理工程师", "entry_date": str(today + timedelta(days=5)), "exit_date": str(today + timedelta(days=60)), "note": "土建专业"},
            {"name": "王五", "role": "监理员", "entry_date": str(today + timedelta(days=10)), "exit_date": None, "note": "至工期结束"},
        ],
        "title": "人员进退场计划表",
        "time_scale": "auto"
    }
    result = ok(client.post(f"/api/projects/{p['id']}/gendocs", json={"template_key": "personnel-gantt", "payload": payload}), 201)
    item = result["item"]
    file_info = result["file"]
    assert item["template_key"] == "personnel-gantt"
    assert item["project_id"] == p["id"]
    assert file_info["download_url"]
    assert file_info["sha256"]
    assert file_info["size"] > 0

    # 下载并验证 docx 内容
    raw = client.get(file_info["download_url"]).content
    assert hashlib.sha256(raw).hexdigest() == file_info["sha256"]
    doc = Document(io.BytesIO(raw))

    # 验证横向页面
    section = doc.sections[0]
    assert section.page_width > section.page_height, "应为横向页面"

    # 验证表格存在
    assert len(doc.tables) >= 1
    table = doc.tables[0]
    # 表格应有 2 行表头 + 3 行数据 = 至少 5 行
    assert len(table.rows) >= 5

    # 验证存在单元格着色（w:shd）
    xml_content = table._tbl.xml
    assert "w:shd" in xml_content, "横道图应有单元格底纹"
    assert "4F81BD" in xml_content or "BFBFBF" in xml_content, "应有蓝色或灰色横道填色"


def test_personnel_gantt_rejects_bad_input(client):
    """验证输入校验：日期倒挂、空行、未知模板。"""
    p = new_project(client)
    today = date.today()

    # exit_date < entry_date → 422
    bad_dates = {"template_key": "personnel-gantt", "payload": {"rows": [
        {"name": "测试", "role": "测试", "entry_date": str(today + timedelta(days=10)), "exit_date": str(today), "note": ""}
    ]}}
    assert client.post(f"/api/projects/{p['id']}/gendocs", json=bad_dates).status_code == 422

    # rows=[] → 422
    empty_rows = {"template_key": "personnel-gantt", "payload": {"rows": []}}
    assert client.post(f"/api/projects/{p['id']}/gendocs", json=empty_rows).status_code == 422

    # 未知 template_key → 404
    unknown = {"template_key": "nonexistent-template", "payload": {}}
    resp = client.post(f"/api/projects/{p['id']}/gendocs", json=unknown)
    assert resp.status_code == 404
    assert resp.json()["code"] == "GENDOC_TEMPLATE_UNKNOWN"

    # 缺少 template_key → 422
    missing = {"payload": {"rows": [{"name": "x", "role": "y", "entry_date": str(today)}]}}
    assert client.post(f"/api/projects/{p['id']}/gendocs", json=missing).status_code == 422


def test_gendoc_does_not_invalidate_review(client):
    """生成附件不应改变项目版本或使复核失效。"""
    p = new_project(client)
    # 记录生成前的项目状态
    version_before = p["version"]
    review_status_before = p["review_status"]

    today = date.today()
    payload = {"rows": [{"name": "赵六", "role": "资料员", "entry_date": str(today), "exit_date": str(today + timedelta(days=90)), "note": ""}]}
    ok(client.post(f"/api/projects/{p['id']}/gendocs", json={"template_key": "personnel-gantt", "payload": payload}), 201)

    # 重新获取项目
    p_after = ok(client.get(f"/api/projects/{p['id']}"))["item"]
    assert p_after["version"] == version_before, "生成附件不应递增项目版本"
    assert p_after["review_status"] == review_status_before, "生成附件不应改变复核状态"


def test_gendoc_history_is_project_scoped(client):
    """附件历史列表按项目隔离。"""
    p1 = new_project(client)
    p2 = new_project(client)
    today = date.today()
    payload = {"rows": [{"name": "测试人员", "role": "监理员", "entry_date": str(today), "exit_date": None, "note": ""}]}

    result = ok(client.post(f"/api/projects/{p1['id']}/gendocs", json={"template_key": "personnel-gantt", "payload": payload}), 201)
    gendoc_id = result["item"]["id"]

    # p1 的历史应包含该附件
    history1 = ok(client.get(f"/api/projects/{p1['id']}/gendocs"))
    assert any(item["id"] == gendoc_id for item in history1["items"])

    # p2 的历史应为空
    history2 = ok(client.get(f"/api/projects/{p2['id']}/gendocs"))
    assert not any(item["id"] == gendoc_id for item in history2["items"])


def test_equipment_list_generates(client):
    """设备清单模板正常生成 docx。"""
    p = new_project(client)
    payload = {
        "rows": [
            {"name": "全站仪", "model_spec": "TS-100", "quantity": 2, "unit": "台", "purpose": "测量放线", "calibration_expiry": "2027-06-30"},
            {"name": "回弹仪", "model_spec": "HT-225", "quantity": 1, "unit": "台", "purpose": "混凝土强度检测", "calibration_expiry": "2027-03-15"},
        ],
        "title": "拟投入主要设备清单"
    }
    result = ok(client.post(f"/api/projects/{p['id']}/gendocs", json={"template_key": "equipment-list", "payload": payload}), 201)
    assert result["item"]["template_key"] == "equipment-list"

    # 下载并验证
    raw = client.get(result["file"]["download_url"]).content
    doc = Document(io.BytesIO(raw))
    assert len(doc.tables) >= 1
    table = doc.tables[0]
    # 应有表头行 + 2行数据
    assert len(table.rows) >= 3
    # 验证内容
    all_text = " ".join(cell.text for row in table.rows for cell in row.cells)
    assert "全站仪" in all_text
    assert "回弹仪" in all_text


def test_existing_export_unchanged(client):
    """确认既有导出链路未受影响（附件不出现在 exports 中）。"""
    p = new_project(client)
    # 生成一个附件后，验证项目详情中 exports 为空（附件不是 export）
    today = date.today()
    payload = {"rows": [{"name": "测试", "role": "测试", "entry_date": str(today), "exit_date": None, "note": ""}]}
    ok(client.post(f"/api/projects/{p['id']}/gendocs", json={"template_key": "personnel-gantt", "payload": payload}), 201)

    detail = ok(client.get(f"/api/projects/{p['id']}"))
    # gendoc 不会出现在 exports 列表中
    assert detail.get("exports", []) == [] or all(e.get("template_key") is None for e in detail.get("exports", []))
