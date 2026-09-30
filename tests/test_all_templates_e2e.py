"""全模板端到端冒烟测试（交付质量闸门）。

不逐模板重复写载荷——用通用样例载荷工厂遍历 registry 中**每一个**已注册模板，
经真实 HTTP API（POST /api/projects/{id}/gendocs）走完「校验 → 生成 → 落盘 → 下载」全链路，
并守住两条全局不变式：
1. 模板端点契约：form_type 合法，行表类下发 columns、段落/章节类下发 fields（数据驱动前端的前提）；
2. 生成附件是纯增量辅助产物：绝不递增项目版本、绝不使复核失效。

覆盖到模板数量随注册表增长自动扩大，无需每次补测试。
"""
import hashlib
import io
import pytest
from fastapi.testclient import TestClient
from docx import Document

from app.core import Settings
from app.main import create_app
from app.gendocs import registry
from tests._genall_helpers import sample_payload_dict

ORIGIN = "http://127.0.0.1:8000"

# 前端数据驱动契约：form_type → 必须下发哪种元数据
ROW_FORMS = {"table", "gantt", "bar", "resume", "hierarchy"}
FIELD_FORMS = {"letter", "sections"}
KNOWN_FORMS = ROW_FORMS | FIELD_FORMS
# 已知例外：equipment-list 早于列式引擎、前端有专属渲染，故无 columns
COLUMN_OPTIONAL_KEYS = {"equipment-list"}


@pytest.fixture
def settings(tmp_path):
    return Settings(tmp_path / "isolated_data_e2e_all", parse_timeout=20)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings), base_url=ORIGIN, headers={"Origin": ORIGIN}) as session:
        yield session


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def new_project(client, business="supervision"):
    return ok(client.post("/api/projects", json={
        "name": "【虚构测试】全模板端到端", "business_type": business,
        "region": "示例地区", "client": "虚构委托单位", "scope": "虚构服务范围",
        "deadline": "2030-12-31T17:00:00+08:00", "facts": {}}), 201)["item"]


# ─────────────────────────── 1. 端点契约（② 前端联调的数据面） ───────────────────────────

def test_templates_endpoint_shape(client):
    """模板列表与注册表一致，且每个模板的 form_type / 元数据满足前端数据驱动渲染契约。"""
    items = ok(client.get("/api/gendocs/templates"))["items"]
    keys = [i["key"] for i in items]
    assert len(items) == len(registry.REGISTRY)
    assert set(keys) == set(registry.REGISTRY), "端点应与注册表严格一致"
    assert len(keys) == len(set(keys)), "存在重复 key"
    assert len(items) >= 45, f"模板总数异常：{len(items)}"

    for item in items:
        form = item["form_type"]
        assert form in KNOWN_FORMS, f"{item['key']} 的 form_type={form} 非法"
        assert item["title"] and item["description"] and item["business_types"]
        if form in FIELD_FORMS:
            assert item.get("fields"), f"{item['key']}({form}) 应下发 fields 供前端渲染字段表单"
        elif form in ROW_FORMS and item["key"] not in COLUMN_OPTIONAL_KEYS:
            assert item.get("columns"), f"{item['key']}({form}) 应下发 columns 供前端渲染行表"


def test_business_type_filter_is_subset(client):
    """按业务线过滤是全体模板的子集，且过滤结果业务线匹配。"""
    all_keys = {i["key"] for i in ok(client.get("/api/gendocs/templates"))["items"]}
    for business in ("supervision", "tis"):
        subset = ok(client.get(f"/api/gendocs/templates?business_type={business}"))["items"]
        assert {i["key"] for i in subset} <= all_keys
        assert all(business in i["business_types"] for i in subset)


# ─────────────────────────── 2. 全模板 API 生成冒烟（③ 端到端） ───────────────────────────

def test_every_template_generates_via_api(client):
    """逐个模板经真实 API 生成 docx：应 201、可下载、sha 校验通过、能被 python-docx 解析出内容。"""
    p = new_project(client)
    failures = []
    for builder in registry._BUILDERS:
        try:
            payload = sample_payload_dict(builder.payload_model)
            result = ok(client.post(
                f"/api/projects/{p['id']}/gendocs",
                json={"template_key": builder.key, "payload": payload}), 201)
            file_info = result["file"]
            assert file_info["size"] > 0 and file_info["download_url"]
            raw = client.get(file_info["download_url"]).content
            assert hashlib.sha256(raw).hexdigest() == file_info["sha256"], f"{builder.key} sha 不符"
            doc = Document(io.BytesIO(raw))
            has_table = len(doc.tables) >= 1
            has_text = any(par.text.strip() for par in doc.paragraphs)
            assert has_table or has_text, f"{builder.key} 生成文档为空"
        except Exception as exc:  # noqa: BLE001  汇总所有失败一次性报出
            failures.append(f"{builder.key}: {type(exc).__name__}: {exc}")
    assert not failures, "以下模板端到端生成失败：\n" + "\n".join(failures)


def test_all_generation_keeps_review_intact(client):
    """连续生成多类模板后，项目版本与复核状态必须纹丝不动（生成附件不触发 store.touch）。"""
    p = new_project(client)
    version_before, review_before = p["version"], p["review_status"]
    for builder in registry._BUILDERS:
        payload = sample_payload_dict(builder.payload_model)
        ok(client.post(f"/api/projects/{p['id']}/gendocs",
                       json={"template_key": builder.key, "payload": payload}), 201)
    after = ok(client.get(f"/api/projects/{p['id']}"))["item"]
    assert after["version"] == version_before, "生成附件不应递增项目版本"
    assert after["review_status"] == review_before, "生成附件不应改变复核状态"
    # 全部落在本项目附件历史中
    history = ok(client.get(f"/api/projects/{p['id']}/gendocs"))["items"]
    assert len(history) == len(registry._BUILDERS)
