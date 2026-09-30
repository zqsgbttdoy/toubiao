"""由独立Verify执行：真实解析、持久化、金额、版本、安全与完整交付链。"""
import hashlib
import io
import json
import sqlite3
import time
import zipfile
from dataclasses import replace

import pytest
from docx import Document
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from app.core import DomainError, Settings, Store, uid
from app.demo import synthetic_docx
from app.files import _docx_blocks, parse_isolated
from app.main import create_app
from app.pricing import calculate_quote

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


def new_project(client, business="supervision", facts=None):
    return ok(client.post("/api/projects", json={"name": "【虚构测试】项目", "business_type": business,
        "region": "示例地区", "client": "虚构委托单位", "scope": "虚构服务范围",
        "deadline": "2030-12-31T17:00:00+08:00", "facts": facts or {}}), 201)["item"]


def refresh(client, p):
    return ok(client.get(f"/api/projects/{p['id']}"))["item"]


def make_docx(text="这是虚构的原始文字用于功能验证。"):
    doc = Document()
    doc.add_paragraph(text)
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "定位样本"
    table.cell(0, 1).text = "表格原文"
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def make_pdf(text=True, pages=1, encrypted=False):
    writer = PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(width=300, height=300)
        if text:
            font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
            page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
            stream = DecodedStreamObject()
            stream.set_data(b"BT /F1 12 Tf 10 200 Td (Synthetic tender text only.) Tj ET")
            page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("fictional-test-password")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def upload_shared(client, raw=None, name="sample.docx"):
    return ok(client.post("/api/files", files={"file": (name, raw or make_docx())}), 201)["item"]


def quote_payload(p, business="supervision", entity_version=0):
    return {"expected_version": p["version"], "entity_version": entity_version,
        "fee_type": "supervision_service" if business == "supervision" else "tis_service",
        "lines": [{"name": "技术服务", "quantity": "1.005", "unit_price": "10.00", "unit": "人月", "basis": "人工确认的虚构测试投入"}],
        "tax_rate": "0.06", "tax_confirmed": True, "tax_note": "测试税率，非行业标准"}


def resource_payload(file_id, business="supervision"):
    return {"name": "【虚构测试】证明", "kind": "qualification", "business_types": [business],
        "description": "合成附件，不表示真实资质", "valid_from": "2020-01-01", "valid_until": "2035-12-31",
        "validity_note": "测试", "scope": "虚构项目范围", "file_ids": [file_id], "tags": ["测试"]}


def complete_project(client, business="supervision"):
    keys = ["staffing", "control_points", "deliverables", "regional_rules", "payment_terms", "commercial_terms",
            "commission_relationship", "independence", "inspection_nodes", "risk_process"]
    facts = {key: {"value": "已人工确认的虚构示例安排", "confirmed": True, "source": "合成测试资料"} for key in keys}
    p = new_project(client, business, facts)
    imported = ok(client.post(f"/api/projects/{p['id']}/documents", data={"expected_version": p["version"]}, files={"file": ("tender.docx", make_docx())}), 201)
    p, doc = imported["project"], imported["item"]
    proof = upload_shared(client)
    m = ok(client.post("/api/materials", json=resource_payload(proof["id"], business)), 201)["item"]
    m = ok(client.post(f"/api/materials/{m['id']}/verify", json={"expected_version": m["version"], "reviewer": "虚构核验人",
        "opinion": "人工核对了合成文件", "status": "approved", "evidence_note": "仅测试原始附件"}))["item"]
    p = ok(client.put(f"/api/projects/{p['id']}/selection", json={"expected_version": p["version"],
        "template_ids": p["selected_template_ids"], "material_ids": [m["id"]], "snippet_ids": []}))["item"]
    r_payload = {"expected_version": p["version"], "text": "投标人必须说明服务方法", "category": "mandatory",
        "mandatory": True, "confirmed": True, "response_status": "responded", "response_note": "已在技术建议书说明",
        "section_id": None, "proof_material_ids": [m["id"]], "document_id": doc["id"], "block_id": doc["blocks"][0]["id"], "source_note": "人工对照原文"}
    response = ok(client.post(f"/api/projects/{p['id']}/requirements", json=r_payload), 201)
    p, requirement = response["project"], response["item"]
    response = ok(client.put(f"/api/projects/{p['id']}/quote", json=quote_payload(p, business)))
    p = response["project"]
    response = ok(client.post(f"/api/projects/{p['id']}/drafts/generate", json={"expected_version": p["version"]}), 201)
    p, draft = response["project"], response["item"]
    r_payload.update(expected_version=p["version"], entity_version=requirement["version"], section_id=draft["sections"][0]["id"])
    response = ok(client.put(f"/api/projects/{p['id']}/requirements/{requirement['id']}", json=r_payload))
    p = response["project"]
    response = ok(client.post(f"/api/projects/{p['id']}/drafts/{draft['id']}/reconcile", json={
        "expected_version": p["version"], "reviewer": "虚构复核人", "note": "已逐章确认条款映射变化不影响正文", "confirmed": True}))
    p, draft = response["project"], response["item"]
    return p, draft, m, proof


def finalize(client, p):
    for category in ("technical", "commercial", "qualification"):
        response = ok(client.put(f"/api/projects/{p['id']}/review/decisions", json={"expected_version": p["version"],
            "entity_version": 0, "category": category, "reviewer": "虚构审核人", "opinion": "完成针对本版本的人工核对", "decision": "approved"}))
        p = response["project"]
    return ok(client.post(f"/api/projects/{p['id']}/review/finalize", json={"expected_version": p["version"], "reviewer": "虚构确认人", "confirmation": True}), 201)


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-1", "1e3", "1.0001", "１２", "+1", "", "1000001"])
def test_invalid_quantity_rejected(bad):
    with pytest.raises(DomainError):
        calculate_quote([{"name": "服务", "quantity": bad, "unit_price": "1.00", "unit": "项", "basis": "测试"}], "0.06")


@pytest.mark.parametrize("bad", ["NaN", "-1", "1.001", "1e2", "1000000001"])
def test_invalid_price_rejected(bad):
    with pytest.raises(DomainError):
        calculate_quote([{"name": "服务", "quantity": "1", "unit_price": bad, "unit": "项", "basis": "测试"}], "0.06")


@pytest.mark.parametrize("bad", ["NaN", "inf", "-0.01", "6", "0.1234567"])
def test_invalid_tax_rejected(bad):
    with pytest.raises(DomainError):
        calculate_quote([{"name": "服务", "quantity": "1", "unit_price": "1.00", "unit": "项", "basis": "测试"}], bad)


def test_line_rounding_precedes_tax():
    row = {"name": "服务", "quantity": "0.005", "unit_price": "1.00", "unit": "项", "basis": "测试"}
    result = calculate_quote([row, row], "0.5")
    assert [x["amount"] for x in result["lines"]] == ["0.01", "0.01"]
    assert (result["subtotal"], result["tax"], result["total"]) == ("0.02", "0.01", "0.03")


def test_transaction_rollback_and_schema(settings):
    store = Store(settings)
    with pytest.raises(RuntimeError):
        with store.transaction() as c:
            store.save(c, "sample", {"id": "rollback"})
            raise RuntimeError("模拟事务回滚")
    with store.transaction() as c:
        assert store.get(c, "sample", "rollback", False) is None
        assert c.execute("PRAGMA user_version").fetchone()[0] == 1


def test_health_and_persistence(client, settings):
    assert ok(client.get("/api/health"))["external_ai"] is False
    p = new_project(client)
    with TestClient(create_app(settings), base_url=ORIGIN, headers={"Origin": ORIGIN}) as second:
        assert ok(second.get(f"/api/projects/{p['id']}"))["item"]["name"] == p["name"]
    assert "+" in p["created_at"]


def test_empty_database_no_automatic_demo(client):
    assert ok(client.get("/api/projects"))["items"] == []
    assert len(ok(client.get("/api/templates"))["items"]) == 18
    assert ok(client.get("/api/dashboard"))["demo"] == 0


def test_security_host_origin_and_fetch_metadata(client):
    assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 403
    assert client.post("/api/projects", headers={"Origin": "https://evil.example"}, json={}).status_code == 403
    assert client.get("/api/health", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.get("/api/health", headers={"Origin": "null"}).status_code == 403
    assert "access-control-allow-origin" not in client.get("/api/health").headers
    response = client.get("/api/health")
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"


def test_mutation_requires_origin(settings):
    with TestClient(create_app(settings), base_url=ORIGIN) as client:
        response = client.post("/api/projects", json={"name": "测试", "business_type": "tis"})
        assert response.status_code == 403
        assert response.json()["code"] == "ORIGIN_REQUIRED"


def test_configurable_port_and_data_path(tmp_path):
    settings = Settings(tmp_path / "isolated", port=8123)
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8123", headers={"Origin": "http://127.0.0.1:8123"}) as client:
        assert ok(client.get("/api/settings"))["port"] == 8123
        assert client.get("/api/health", headers={"Host": "127.0.0.1:8000"}).status_code == 403


def test_private_data_not_static(client):
    for path in ("/data/database.sqlite3", "/static/../data/database.sqlite3", "/api/files/not-a-file/download"):
        assert client.get(path).status_code == 404


def test_project_version_unknown_fields_and_timezone(client):
    p = new_project(client)
    payload = {key: p[key] for key in ("name", "business_type", "region", "client", "scope", "deadline", "facts")}
    payload.update(expected_version=p["version"], name="新名称")
    changed = ok(client.put(f"/api/projects/{p['id']}", json=payload))["item"]
    assert changed["version"] == p["version"] + 1
    assert client.put(f"/api/projects/{p['id']}", json=payload).status_code == 409
    payload.update(expected_version=changed["version"], review_status="reviewed")
    assert client.put(f"/api/projects/{p['id']}", json=payload).status_code == 422
    payload.pop("review_status")
    payload["deadline"] = "2030-01-01T10:00:00"
    assert client.put(f"/api/projects/{p['id']}", json=payload).status_code == 422


def test_archive_and_delete(client):
    p = new_project(client)
    assert client.request("DELETE", f"/api/projects/{p['id']}", json={"expected_version": p["version"]}).status_code == 409
    p = ok(client.post(f"/api/projects/{p['id']}/archive", json={"expected_version": p["version"], "archived": True}))["item"]
    assert client.post(f"/api/projects/{p['id']}/drafts/generate", json={"expected_version": p["version"]}).status_code == 409
    assert ok(client.request("DELETE", f"/api/projects/{p['id']}", json={"expected_version": p["version"]}))["deleted"]
    assert client.get(f"/api/projects/{p['id']}").status_code == 404


@pytest.mark.parametrize("business", ["supervision", "tis"])
def test_real_docx_upload_candidates_and_locations(client, business):
    p = new_project(client, business)
    raw = synthetic_docx(business)
    response = ok(client.post(f"/api/projects/{p['id']}/documents", data={"expected_version": p["version"]}, files={"file": ("../../恶意名.docx", raw)}), 201)
    doc = response["item"]
    assert doc["title"] == "恶意名.docx"
    assert {b["locator"]["kind"] for b in doc["blocks"]} == {"paragraph", "table"}
    assert all("page" not in b["locator"] for b in doc["blocks"])
    assert response["requirements"] and all(not r["confirmed"] for r in response["requirements"])
    file = ok(client.get(f"/api/files/{doc['file_id']}"))["item"]
    assert file["sha256"] == hashlib.sha256(raw).hexdigest()
    assert client.get(file["download_url"]).content == raw
    assert "blobs" not in json.dumps(file, ensure_ascii=False)


def test_pdf_text_pages_scan_and_encryption(client):
    text_file = upload_shared(client, make_pdf(), "text.pdf")
    assert text_file["blocks"][0]["locator"] == {"kind": "page", "page": 1}
    scanned = upload_shared(client, make_pdf(text=False), "scan.pdf")
    assert scanned["parse_status"] == "needs_manual_excerpt"
    response = client.post("/api/files", files={"file": ("encrypted.pdf", make_pdf(encrypted=True))})
    assert response.status_code == 422
    assert response.json()["code"] == "ENCRYPTED_FILE"


def test_pdf_page_limit(settings, tmp_path):
    path = tmp_path / "pages.pdf"
    path.write_bytes(make_pdf(pages=2))
    with pytest.raises(DomainError, match="最多允许"):
        parse_isolated(path, ".pdf", replace(settings, max_pdf_pages=1))


@pytest.mark.parametrize("name,raw", [("old.doc", b"abc"), ("macro.docm", b"PK000"), ("bad.docx", b"PK\x03\x04invalid"), ("bad.pdf", b"%PDF-1.7 broken"), ("fake.pdf", b"html"), ("blank.docx", b"")])
def test_invalid_uploads_fail_explicitly(client, name, raw):
    response = client.post("/api/files", files={"file": (name, raw)})
    assert response.status_code in (415, 422)
    assert set(response.json()) == {"code", "message"}


def test_upload_size_limit(client):
    response = client.post("/api/files", files={"file": ("huge.pdf", b"%PDF-" + b"x" * (20 * 1024 * 1024))})
    assert response.status_code == 413


@pytest.mark.parametrize("member", ["../escape.xml", "word/vbaProject.bin", "/absolute.xml", "C:/escape.xml"])
def test_unsafe_docx_members(member):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(member, b"bad")
    with pytest.raises(DomainError):
        _docx_blocks(output.getvalue())


def test_zip_bomb_and_xml_entities():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b"x" * (2 * 1024 * 1024))
    with pytest.raises(DomainError) as exc:
        _docx_blocks(output.getvalue())
    assert exc.value.code == "ZIP_LIMIT"
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("word/document.xml", b'<!DOCTYPE a [<!ENTITY e SYSTEM "file:///secret">]><a>&e;</a>')
    with pytest.raises(DomainError) as exc:
        _docx_blocks(output.getvalue())
    assert exc.value.code == "UNSAFE_XML"


def slow_worker(path, extension, max_pages, output):
    time.sleep(3)


def test_parser_timeout_terminates_child(monkeypatch, settings, tmp_path):
    import app.files as files
    monkeypatch.setattr(files, "_parse_worker", slow_worker)
    path = tmp_path / "slow.docx"
    path.write_bytes(make_docx())
    with pytest.raises(DomainError) as exc:
        parse_isolated(path, ".docx", replace(settings, parse_timeout=0.02))
    assert exc.value.code == "PARSE_TIMEOUT"


def test_manual_excerpt_html_is_data_and_addendum_versions(client):
    p = new_project(client)
    text = '<script>alert("fictional")</script> 必须人工核验。'
    first = ok(client.post(f"/api/projects/{p['id']}/documents/excerpts", json={"expected_version": p["version"], "title": "人工摘录", "text": text, "source_note": "扫描件人工摘录"}), 201)
    assert first["item"]["blocks"][0]["text"] == text
    second = ok(client.post(f"/api/projects/{p['id']}/documents/excerpts", json={"expected_version": first["project"]["version"], "title": "补遗", "text": "必须追加说明。", "source_note": "补遗人工摘录", "replaces_document_id": first["item"]["id"]}), 201)
    assert second["item"]["source_version"] == 2
    assert first["item"]["source_family_id"] == second["item"]["source_family_id"]
    assert len(ok(client.get(f"/api/projects/{p['id']}/documents"))["items"]) == 2


def test_cross_project_document_reference_rejected(client):
    a, b = new_project(client), new_project(client)
    doc = ok(client.post(f"/api/projects/{a['id']}/documents/excerpts", json={"expected_version": a["version"], "title": "原文", "text": "测试原文", "source_note": "人工"}), 201)["item"]
    response = client.post(f"/api/projects/{b['id']}/requirements", json={"expected_version": b["version"], "text": "测试", "category": "delivery", "document_id": doc["id"], "block_id": doc["blocks"][0]["id"]})
    assert response.status_code == 404


def test_template_copy_edit_review_history(client):
    template = ok(client.get("/api/templates/builtin-tis"))["item"]
    copied = ok(client.post(f"/api/templates/{template['id']}/copy", json={"expected_version": template["version"], "name": "自定义虚构模板"}), 201)["item"]
    fields = {key: copied[key] for key in ("name", "business_types", "sections", "source", "tags")}
    fields["sections"][0]["body"] += "\n自定义内容"
    fields["expected_version"] = copied["version"]
    updated = ok(client.put(f"/api/templates/{copied['id']}", json=fields))["item"]
    assert updated["version"] == 2 and not updated["builtin"]
    verified = ok(client.post(f"/api/templates/{copied['id']}/verify", json={"expected_version": 2, "reviewer": "测试", "opinion": "人工检查", "status": "approved", "evidence_note": "模板原文"}))["item"]
    assert verified["verification"]["content_version"] == verified["version"]
    assert len(ok(client.get(f"/api/templates/{copied['id']}/versions"))["items"]) == 3
    assert client.put(f"/api/templates/{copied['id']}", json=fields).status_code == 409
    fields["expected_version"] = template["version"]
    assert client.put(f"/api/templates/{template['id']}", json=fields).status_code == 409


def test_snippet_selection_search_insertion_and_origin(client):
    p, draft, material, proof = complete_project(client)
    source = upload_shared(client)
    payload = {"title": "历史检查素材", "content": "用户选择的历史措施，不代表实际检测结果。", "business_types": ["supervision"],
        "tags": ["闭环"], "source_file_id": source["id"], "source_block_ids": [source["blocks"][0]["id"]]}
    snippet = ok(client.post("/api/snippets", json=payload), 201)["item"]
    assert snippet["source_version"] == source["version"]
    assert ok(client.get("/api/snippets?q=检查&tag=闭环&business_type=supervision"))["items"]
    section = draft["sections"][0]
    result = ok(client.post(f"/api/projects/{p['id']}/drafts/{draft['id']}/sections/{section['id']}/insert-snippet", json={
        "expected_version": p["version"], "entity_version": section["version"], "snippet_id": snippet["id"], "snippet_version": snippet["version"]}))
    assert snippet["content"] in result["item"]["body"]
    assert {"kind": "snippet", "id": snippet["id"], "version": snippet["version"]} in result["item"]["references"]
    payload["source_block_ids"] = [uid()]
    assert client.post("/api/snippets", json=payload).status_code == 422


@pytest.mark.parametrize("business", ["supervision", "tis"])
def test_complete_review_export_original_hash_and_frozen_snapshot(client, business):
    p, draft, material, proof = complete_project(client, business)
    risk = ok(client.get(f"/api/projects/{p['id']}/review"))["risk_report"]
    assert risk["blocking_count"] == 0, risk
    body = "\n".join(s["body"] for s in draft["sections"])
    assert ("TIS技术服务" in body) if business == "tis" else ("监理职责" in body)
    result = finalize(client, p)
    p, frozen = result["project"], result["item"]
    assert frozen["immutable"] and p["review_status"] == "reviewed"
    export = ok(client.post(f"/api/projects/{p['id']}/exports", json={"expected_version": p["version"], "mode": "reviewed"}), 201)["item"]
    assert len(export["files"]) == 4
    # 创建响应与列表只返回摘要；完整冻结快照只能通过详情接口读取。
    assert "snapshot" not in export
    assert export["download_url"] == next(f["download_url"] for f in export["files"] if f["kind"] == "package")
    frozen_export = ok(client.get(f"/api/projects/{p['id']}/exports/{export['id']}"))["item"]
    assert frozen_export["snapshot"]["project"]["version"] == p["version"]
    package = next(f for f in export["files"] if f["kind"] == "package")
    raw = client.get(package["download_url"]).content
    assert hashlib.sha256(raw).hexdigest() == package["sha256"]
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        for entry in manifest["files"]:
            assert hashlib.sha256(archive.read(entry["name"])).hexdigest() == entry["sha256"]
        commercial = Document(io.BytesIO(archive.read("commercial.docx")))
        paragraphs = "\n".join(p.text for p in commercial.paragraphs)
        assert draft["quote_snapshot"]["total"] in paragraphs
        attachment = next(x for x in manifest["files"] if x.get("file_id") == proof["id"])
        assert archive.read(attachment["name"]) == client.get(proof["download_url"]).content
    section = draft["sections"][0]
    edit = ok(client.put(f"/api/projects/{p['id']}/drafts/{draft['id']}/sections/{section['id']}", json={"expected_version": p["version"],
        "entity_version": section["version"], "body": section["body"] + "\n新增人工说明", "references": section["references"], "requirement_ids": section["requirement_ids"]}))
    p = edit["project"]
    assert p["review_status"] == "pending"
    assert client.post(f"/api/projects/{p['id']}/exports", json={"expected_version": p["version"], "mode": "reviewed"}).status_code == 409
    assert client.get(package["download_url"]).content == raw
    assert ok(client.get(f"/api/projects/{p['id']}/exports/{export['id']}"))["item"]["snapshot"] == frozen_export["snapshot"]
    assert all("snapshot" not in row for row in ok(client.get(f"/api/projects/{p['id']}/exports"))["items"])
    assert all("snapshot" not in row for row in ok(client.get(f"/api/projects/{p['id']}"))["exports"])


def test_review_cannot_be_self_reported_or_skip_human_records(client):
    p = new_project(client)
    assert client.post(f"/api/projects/{p['id']}/review/finalize", json={"expected_version": p["version"], "reviewer": "测试", "confirmation": True}).status_code == 409
    sent = ok(client.post(f"/api/projects/{p['id']}/exports", json={"expected_version": p["version"], "mode": "review"}), 201)["item"]
    assert "snapshot" not in sent
    assert ok(client.get(f"/api/projects/{p['id']}/exports/{sent['id']}"))["item"]["snapshot"]["risk_report"]["blocking_count"] > 0
    p, draft, material, proof = complete_project(client)
    assert client.post(f"/api/projects/{p['id']}/review/finalize", json={"expected_version": p["version"], "reviewer": "测试", "confirmation": True}).json()["code"] == "REVIEW_RECORDS_INCOMPLETE"
    assert client.post(f"/api/projects/{p['id']}/review/finalize", json={"expected_version": p["version"], "reviewer": "测试", "confirmation": False}).status_code == 422


def test_regeneration_requires_confirmation_preserves_old_manual_text(client):
    p, draft, material, proof = complete_project(client)
    section = draft["sections"][0]
    result = ok(client.put(f"/api/projects/{p['id']}/drafts/{draft['id']}/sections/{section['id']}", json={"expected_version": p["version"],
        "entity_version": section["version"], "body": section["body"] + "\n不可静默覆盖的人工文字", "references": section["references"], "requirement_ids": section["requirement_ids"]}))
    p = result["project"]
    assert client.post(f"/api/projects/{p['id']}/drafts/generate", json={"expected_version": p["version"]}).status_code == 409
    newer = ok(client.post(f"/api/projects/{p['id']}/drafts/generate", json={"expected_version": p["version"], "confirm_regenerate": True}), 201)
    assert newer["item"]["generation"] == 2
    old = ok(client.get(f"/api/projects/{p['id']}/drafts/{draft['id']}"))["item"]
    assert "不可静默覆盖的人工文字" in old["sections"][0]["body"]
    assert old["is_current"] is False


def test_quote_update_invalidates_draft_and_cannot_reconcile_away(client):
    p, draft, material, proof = complete_project(client)
    payload = quote_payload(p, entity_version=draft["quote_snapshot"]["version"])
    payload["lines"][0]["unit_price"] = "20.00"
    p = ok(client.put(f"/api/projects/{p['id']}/quote", json=payload))["project"]
    current = ok(client.get(f"/api/projects/{p['id']}/drafts"))["current"]
    assert current["stale"] is True
    response = client.post(f"/api/projects/{p['id']}/drafts/{draft['id']}/reconcile", json={"expected_version": p["version"], "reviewer": "测试", "note": "试图绕过报价版本", "confirmed": True})
    assert response.status_code == 409 and response.json()["code"] == "QUOTE_REGEN_REQUIRED"


def test_quote_text_cannot_be_forged_in_section_editor(client):
    p, draft, material, proof = complete_project(client)
    section = next(s for s in draft["sections"] if s["contains_quote"])
    response = client.put(f"/api/projects/{p['id']}/drafts/{draft['id']}/sections/{section['id']}", json={"expected_version": p["version"],
        "entity_version": section["version"], "body": "伪造总价1元", "references": section["references"]})
    assert response.status_code == 422


def test_material_change_resets_verification_and_related_project(client):
    p, draft, material, proof = complete_project(client)
    reviewed = finalize(client, p)
    p = reviewed["project"]
    payload = resource_payload(proof["id"])
    payload.update(expected_version=material["version"], valid_until="2020-12-31")
    material = ok(client.put(f"/api/materials/{material['id']}", json=payload))["item"]
    assert material["review_status"] == "pending" and material["verification"] is None
    current = ok(client.get(f"/api/projects/{p['id']}"))
    assert current["item"]["version"] > p["version"]
    assert current["item"]["review_status"] == "pending"
    codes = {x["code"] for x in current["risk_report"]["issues"]}
    assert {"CERTIFICATE_EXPIRED", "MATERIAL_UNVERIFIED", "DRAFT_STALE", "SOURCE_VERSION_STALE"} <= codes


def test_missing_attachment_and_hash_tampering_block_review(client, settings):
    p, draft, material, proof = complete_project(client)
    (settings.data_dir / "blobs" / proof["id"]).write_bytes(b"tampered")
    risk = ok(client.get(f"/api/projects/{p['id']}/review"))["risk_report"]
    assert "ATTACHMENT_HASH_MISMATCH" in {x["code"] for x in risk["issues"]}
    assert client.get(proof["download_url"]).status_code == 409
    assert client.post("/api/backups").status_code == 409


def test_scoring_gap_is_not_blocking(client):
    p, draft, material, proof = complete_project(client)
    response = ok(client.post(f"/api/projects/{p['id']}/requirements", json={"expected_version": p["version"], "text": "可选评分点",
        "category": "scoring", "confirmed": True, "mandatory": False, "response_status": "gap"}), 201)
    p = response["project"]
    ok(client.post(f"/api/projects/{p['id']}/drafts/{draft['id']}/reconcile", json={"expected_version": p["version"], "reviewer": "测试", "note": "已核对评分缺口", "confirmed": True}))
    report = ok(client.get(f"/api/projects/{p['id']}/review"))["risk_report"]
    assert report["scoring_count"] == 1
    assert report["blocking_count"] == 0


def test_backup_sqlite_snapshot_matches_all_attachments(client, tmp_path):
    p, draft, material, proof = complete_project(client)
    backup = ok(client.post("/api/backups"), 201)["item"]
    raw = client.get(backup["download_url"]).content
    assert hashlib.sha256(raw).hexdigest() == backup["sha256"]
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        manifest = json.loads(archive.read("backup_manifest.json"))
        assert hashlib.sha256(archive.read("database.sqlite3")).hexdigest() == manifest["database_sha256"]
        database = tmp_path / "restored.sqlite3"
        database.write_bytes(archive.read("database.sqlite3"))
        connection = sqlite3.connect(database)
        try:
            files = [json.loads(row[0]) for row in connection.execute("SELECT data FROM entities WHERE kind='file'")]
            projects = list(connection.execute("SELECT data FROM entities WHERE kind='project'"))
            assert projects
        finally:
            connection.close()
        for file in files:
            assert hashlib.sha256(archive.read("blobs/" + file["id"])).hexdigest() == file["sha256"]
        assert "停止" in manifest["restore"]


def test_demo_requires_confirmation_is_fictional_and_idempotent(client):
    assert client.post("/api/demo/load", json={"confirmation": False}).status_code == 422
    first = ok(client.post("/api/demo/load", json={"confirmation": True}))
    assert len(first["items"]) == 2 and all(p["is_demo"] and "虚构" in p["name"] for p in first["items"])
    second = ok(client.post("/api/demo/load", json={"confirmation": True}))
    assert second["already_loaded"]
    assert len(ok(client.get("/api/projects"))["items"]) == 2


def test_openapi_has_concrete_requests_responses_and_no_remote_docs(client):
    schema = ok(client.get("/api/openapi.json"))
    for path in ("/api/projects/{project_id}/quote", "/api/projects/{project_id}/drafts/generate", "/api/materials", "/api/backups"):
        assert path in schema["paths"]
    project_schema = schema["paths"]["/api/projects/{project_id}"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert "risk_report" in project_schema["properties"]
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404


def test_requirement_and_section_links_stay_bidirectional(client):
    p, draft, material, proof = complete_project(client)
    requirement = ok(client.get(f"/api/projects/{p['id']}/requirements"))["items"][0]
    first, target = draft["sections"][:2]
    assert requirement["id"] in first["requirement_ids"]
    payload = {"expected_version": p["version"], "entity_version": target["version"],
        "body": target["body"], "references": target["references"], "requirement_ids": [requirement["id"]]}
    moved = ok(client.put(f"/api/projects/{p['id']}/drafts/{draft['id']}/sections/{target['id']}", json=payload))
    p = moved["project"]
    current = ok(client.get(f"/api/projects/{p['id']}"))
    requirement = current["requirements"][0]
    assert requirement["section_id"] == target["id"]
    assert requirement["id"] not in current["draft"]["sections"][0]["requirement_ids"]
    assert current["draft"]["stale"]
    payload["expected_version"] = p["version"]
    assert client.put(f"/api/projects/{p['id']}/drafts/{draft['id']}/sections/{target['id']}", json=payload).status_code == 409
    ok(client.request("DELETE", f"/api/projects/{p['id']}/requirements/{requirement['id']}",
        json={"expected_version": p["version"], "entity_version": requirement["version"]}))
    current = ok(client.get(f"/api/projects/{p['id']}/drafts"))["current"]
    assert all(requirement["id"] not in s["requirement_ids"] for s in current["sections"])


def test_new_source_revokes_previous_completeness_confirmation(client):
    p = new_project(client, facts={"source_completeness": {"value": "已人工核对原来源", "confirmed": True, "source": "旧版本核对记录"}})
    result = ok(client.post(f"/api/projects/{p['id']}/documents", data={"expected_version": p["version"]},
        files={"file": ("new_scan.pdf", make_pdf(text=False))}), 201)
    assert result["project"]["facts"]["source_completeness"]["confirmed"] is False
    report = ok(client.get(f"/api/projects/{p['id']}/review"))["risk_report"]
    assert "SOURCE_INCOMPLETE" in {issue["code"] for issue in report["issues"]}


def test_quote_api_rejects_fee_mix_and_client_totals(client):
    p = new_project(client)
    payload = quote_payload(p)
    payload["fee_type"] = "tis_service"
    assert client.put(f"/api/projects/{p['id']}/quote", json=payload).status_code == 422
    payload["fee_type"] = "supervision_service"
    payload["total"] = "1.00"
    assert client.put(f"/api/projects/{p['id']}/quote", json=payload).status_code == 422
    payload.pop("total")
    payload["tax_confirmed"] = False
    saved = ok(client.put(f"/api/projects/{p['id']}/quote", json=payload))
    assert saved["item"]["total"] == "10.65"
    report = ok(client.get(f"/api/projects/{p['id']}/review"))["risk_report"]
    assert "QUOTE_INCOMPLETE" in {issue["code"] for issue in report["issues"]}


def test_public_static_directory_cannot_be_data_directory():
    from app.core import ROOT
    with pytest.raises(ValueError, match="公开静态"):
        Settings(ROOT / "app" / "static" / "private-data")


def test_list_endpoints_strip_heavy_payloads(client):
    p, draft, material, proof = complete_project(client)
    drafts = ok(client.get(f"/api/projects/{p['id']}/drafts"))
    assert all("input_snapshot" not in row and "sections" not in row and "quote_snapshot" not in row for row in drafts["items"])
    summary = next(row for row in drafts["items"] if row["id"] == draft["id"])
    assert summary["is_current"] is True and summary["stale"] is False
    assert summary["section_count"] == len(draft["sections"])
    assert drafts["current"]["input_snapshot"]["project"]["name"] == p["name"]
    assert ok(client.get(f"/api/projects/{p['id']}/drafts/{draft['id']}"))["item"]["sections"][0]["body"]
    frozen = finalize(client, p)
    review = ok(client.get(f"/api/projects/{p['id']}/review"))
    assert all("snapshot" not in row for row in review["snapshots"])
    entry = next(row for row in review["snapshots"] if row["id"] == frozen["item"]["id"])
    assert entry["frozen_at"] and entry["reviewer"] and entry["project_version"] == frozen["project"]["version"]
    assert ok(client.get(f"/api/projects/{p['id']}/review/snapshots/{entry['id']}"))["item"]["snapshot"]["project"]["id"] == p["id"]
    assert client.get(f"/api/projects/{p['id']}/review/snapshots/missing").status_code == 404
    listed = ok(client.get("/api/files"))["items"]
    assert listed and all("blocks" not in row for row in listed)
    assert ok(client.get(f"/api/files/{proof['id']}"))["item"]["blocks"]


@pytest.mark.parametrize("field,value", [("text", "含\u0000截断的原文"), ("title", "标题\u001b[0m"), ("source_note", "备注\u007f")])
def test_control_characters_rejected(client, field, value):
    p = new_project(client)
    payload = {"expected_version": p["version"], "title": "人工摘录", "text": "必须人工核对的虚构原文。", "source_note": "人工"}
    payload[field] = value
    response = client.post(f"/api/projects/{p['id']}/documents/excerpts", json=payload)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    payload[field] = value.replace("\u0000", "").replace("\u001b", "").replace("\u007f", "")
    assert ok(client.post(f"/api/projects/{p['id']}/documents/excerpts", json=payload), 201)["item"]["blocks"][0]["text"]


def test_section_edit_syncs_many_requirements_in_single_pass(client, settings):
    p, draft, material, proof = complete_project(client)
    first, target = draft["sections"][:2]
    ids = [ok(client.get(f"/api/projects/{p['id']}/requirements"))["items"][0]["id"]]
    for index in range(4):
        current = ok(client.get(f"/api/projects/{p['id']}"))["item"]
        created = ok(client.post(f"/api/projects/{p['id']}/requirements", json={"expected_version": current["version"],
            "text": f"批量移动回归条款{index}", "category": "delivery", "section_id": first["id"]}), 201)
        ids.append(created["item"]["id"])
    detail = ok(client.get(f"/api/projects/{p['id']}"))
    sections = {s["id"]: s for s in detail["draft"]["sections"]}
    marker = event_marker(settings)
    moved = ok(client.put(f"/api/projects/{p['id']}/drafts/{draft['id']}/sections/{target['id']}", json={
        "expected_version": detail["item"]["version"], "entity_version": sections[target["id"]]["version"],
        "body": sections[target["id"]]["body"], "references": sections[target["id"]]["references"], "requirement_ids": ids}))
    assert moved["item"]["requirement_ids"] == ids
    current = ok(client.get(f"/api/projects/{p['id']}"))
    assert {r["id"]: r["section_id"] for r in current["requirements"]} == {rid: target["id"] for rid in ids}
    sections = {s["id"]: s for s in current["draft"]["sections"]}
    assert set(sections[target["id"]]["requirement_ids"]) == set(ids)
    assert not set(sections[first["id"]]["requirement_ids"]) & set(ids)
    # 批量化后，本次编辑只能产生“源章节一次 + 草稿一次”同步修订，而不是每条条款各一次。
    assert link_events(settings, marker, "section") == {first["id"]: 1}
    assert link_events(settings, marker, "draft") == {draft["id"]: 1}


def event_marker(settings):
    database = sqlite3.connect(settings.data_dir / "database.sqlite3")
    try:
        return database.execute("SELECT COALESCE(MAX(id), 0) FROM events").fetchone()[0]
    finally:
        database.close()


def link_events(settings, marker, kind):
    database = sqlite3.connect(settings.data_dir / "database.sqlite3")
    try:
        rows = database.execute("SELECT entity_id, COUNT(*) FROM events WHERE id>? AND action=? GROUP BY entity_id",
                                (marker, f"{kind}.requirement_link_changed")).fetchall()
    finally:
        database.close()
    return dict(rows)
