"""不可变导出与SQLite一致性备份。原始引用附件逐字节保留。"""
import hashlib
import io
import json
import re
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from docx import Document
from docx.shared import Pt
from docx.oxml.ns import qn
from fastapi import APIRouter, Request
from fastapi.responses import Response

from .core import DomainError, dumps, now, uid
from .files import blob_bytes, safe_name, store_blob
from .review import check_risks, frozen_snapshot
from .schemas import ExportRequest

router = APIRouter(prefix="/api", tags=["成果导出与本地备份"])
DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
# 导出列表与项目详情只返回摘要；snapshot 完整冻结内容仅通过 GET /exports/{export_id} 获取。
EXPORT_SUMMARY_KEYS = ("id", "project_id", "version", "created_at", "updated_at", "mode",
                       "project_version", "review_snapshot_id", "manifest", "files", "immutable")


def export_summary(export):
    summary = {key: export.get(key) for key in EXPORT_SUMMARY_KEYS}
    summary["download_url"] = next((f["download_url"] for f in export.get("files", [])
                                    if f.get("kind") == "package" and f.get("download_url")), None)
    return summary


def clean_xml(text):
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]", "", str(text))


def make_docx(snapshot, categories, title, mode):
    document = Document()
    style = document.styles["Normal"]
    style.font.name = "宋体"
    style.font.size = Pt(11)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    p = snapshot["project"]
    document.add_heading(clean_xml(p["name"]), 0)
    document.add_heading(title, 1)
    label = "已内部复核版（仅人工记录）" if mode == "reviewed" else "送审稿（非可直接提交版本）"
    document.add_paragraph(label)
    document.add_paragraph(f"项目版本：{p['version']}；冻结时点：{snapshot['frozen_at']}")
    document.add_paragraph(clean_xml(snapshot["disclaimer"]))
    document.add_heading("目录", 1)
    draft = snapshot.get("draft")
    sections = [s for s in (draft["sections"] if draft else []) if s["category"] in categories]
    for index, section in enumerate(sections, 1):
        document.add_paragraph(f"{index}. {clean_xml(section['title'])}")
    if not sections:
        document.add_paragraph("【待填：此分类尚无章节】")
    for section in sections:
        document.add_heading(clean_xml(section["title"]), 1)
        for paragraph in section["body"].splitlines():
            document.add_paragraph(clean_xml(paragraph))
        document.add_paragraph("来源与版本：" + "; ".join(f"{r['kind']}:{r['id']} v{r['version']}" for r in section["references"]))
    if "commercial" in categories:
        document.add_heading("权威报价快照", 1)
        quote = draft.get("quote_snapshot") if draft else snapshot["inputs"]["quote"]
        if quote:
            table = document.add_table(rows=1, cols=6)
            table.style = "Table Grid"
            headers = ["项目", "数量", "单位", "单价（元）", "金额（元）", "依据"]
            for cell, text in zip(table.rows[0].cells, headers):
                cell.text = text
            for line in quote["lines"]:
                values = [line["name"], line["quantity"], line["unit"], line["unit_price"], line["amount"], line["basis"]]
                for cell, text in zip(table.add_row().cells, values):
                    cell.text = clean_xml(text)
            document.add_paragraph(f"不含税合计：{quote['subtotal']}元；税率：{quote['tax_rate']}；税额：{quote['tax']}元；含税总价：{quote['total']}元")
        else:
            document.add_paragraph("【待填：报价】")
    if "qualification" in categories:
        document.add_heading("原始附件目录（详见ZIP附件）", 1)
        for file in snapshot["files"]:
            document.add_paragraph(clean_xml(f"{file['name']} | ID {file['id']} | SHA256 {file['sha256']}"))
    document.add_heading("内部复核记录", 1)
    for record in snapshot["review_records"]:
        document.add_paragraph(clean_xml(f"{record['category']}：{record['reviewer']}；{record['decision']}；{record['opinion']}；项目版本{record['project_version']}"))
    document.add_heading("缺项与风险清单", 1)
    for issue in snapshot["risk_report"]["issues"]:
        document.add_paragraph(clean_xml(f"[{issue['severity']}] {issue['code']}：{issue['message']}"))
    if not snapshot["risk_report"]["issues"]:
        document.add_paragraph("规则未发现缺项，不构成合规或中标保证。")
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


def build_package(store, snapshot, mode):
    outputs = []
    for key, title, categories in [
        ("technical", "技术建议书及响应复核表", {"technical", "response", "internal"}),
        ("commercial", "商务文件", {"commercial"}),
        ("qualification", "资格证明目录", {"qualification"}),
    ]:
        outputs.append((key + ".docx", make_docx(snapshot, categories, title, mode), DOCX_MEDIA, key))
    archive_output = io.BytesIO()
    manifest = {"project_id": snapshot["project"]["id"], "project_version": snapshot["project"]["version"],
                "mode": mode, "frozen_at": snapshot["frozen_at"], "files": [], "missing_attachments": []}
    with zipfile.ZipFile(archive_output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, raw, media, key in outputs:
            archive.writestr(name, raw)
            manifest["files"].append({"name": name, "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)})
        for file in snapshot["files"]:
            try:
                raw = blob_bytes(store, file)
            except DomainError as exc:
                if mode == "reviewed":
                    raise
                manifest["missing_attachments"].append({"file_id": file["id"], "name": file["name"], "reason": exc.message})
                continue
            name = "attachments/" + file["id"] + "_" + safe_name(file["name"])
            archive.writestr(name, raw)
            manifest["files"].append({"name": name, "file_id": file["id"], "source_version": file["version"],
                                      "sha256": file["sha256"], "size": len(raw)})
        missing = "\n".join(f"[{x['severity']}] {x['code']} {x['message']}" for x in snapshot["risk_report"]["issues"]) or "未发现规则缺项，仍须人工负责。"
        for missing_file in manifest["missing_attachments"]:
            missing += f"\n[blocking] {missing_file['name']}：{missing_file['reason']}"
        snapshot_raw = dumps(snapshot).encode("utf-8")
        archive.writestr("snapshot.json", snapshot_raw)
        archive.writestr("missing_items.txt", missing.encode("utf-8-sig"))
        manifest["snapshot_sha256"] = hashlib.sha256(snapshot_raw).hexdigest()
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
    outputs.append(("bid_package.zip", archive_output.getvalue(), "application/zip", "package"))
    return outputs, manifest


@router.get("/projects/{project_id}/exports")
def export_list(project_id: str, request: Request):
    store = request.app.state.store
    with store.transaction() as c:
        p = store.project(c, project_id)
        return {"items": [export_summary(e) for e in store.all(c, "export", project_id)], "project_version": p["version"]}


@router.post("/projects/{project_id}/exports", status_code=201)
def export_create(project_id: str, body: ExportRequest, request: Request):
    store = request.app.state.store
    with store.transaction() as c:
        p = store.project(c, project_id, body.expected_version)
        if body.mode == "reviewed":
            if p["review_status"] != "reviewed" or not p.get("current_review_id"):
                raise DomainError("NOT_REVIEWED", "当前项目未完成内部复核，只能导出送审稿", 409)
            reviewed = store.child(c, "review_snapshot", p["current_review_id"], project_id)
            if reviewed["project_version"] != p["version"]:
                raise DomainError("REVIEW_STALE", "冻结复核与当前项目版本不一致", 409)
            if check_risks(store, c, p)["blocking_count"]:
                raise DomainError("REVIEW_NOW_BLOCKED", "当前出现证照到期或附件完整性等阻断风险，不能新建已复核版导出；原冻结记录保持不变", 409)
            snapshot = reviewed["snapshot"]
        else:
            snapshot = frozen_snapshot(store, c, p, check_risks(store, c, p))
        outputs, manifest = build_package(store, snapshot, body.mode)
        files = []
        for name, raw, media, kind in outputs:
            file = store_blob(store, c, raw, name, media, purpose="export")
            files.append({"kind": kind, **file})
        item = store.save(c, "export", {"id": uid(), "project_id": project_id, "mode": body.mode,
            "project_version": p["version"], "review_snapshot_id": p.get("current_review_id") if body.mode == "reviewed" else None,
            "snapshot": snapshot, "manifest": manifest, "files": files, "immutable": True})
        return {"item": export_summary(item), "project_version": p["version"]}


@router.get("/projects/{project_id}/exports/{export_id}")
def export_detail(project_id: str, export_id: str, request: Request):
    store = request.app.state.store
    with store.transaction() as c:
        store.project(c, project_id)
        return {"item": store.child(c, "export", export_id, project_id)}


@router.post("/backups", status_code=201)
def backup_create(request: Request):
    store = request.app.state.store
    with store.lock, tempfile.TemporaryDirectory(prefix="backup_", dir=store.root) as directory:
        path = Path(directory) / "database.sqlite3"
        source = store.connect()
        destination = sqlite3.connect(path)
        try:
            source.backup(destination)
            # 备份产物不递归打包；仅移除副本中的旧备份下载目录，业务记录与附件完整保留。
            destination.execute("DELETE FROM entities WHERE kind='backup'")
            destination.execute("DELETE FROM revisions WHERE kind='backup'")
            destination.commit()
            files = [json.loads(row[0]) for row in destination.execute("SELECT data FROM entities WHERE kind='file'")]
        finally:
            destination.close()
            source.close()
        output = io.BytesIO()
        manifest = {"schema_version": 1, "created_at": now(), "files": [],
                    "restore": "停止所有本软件进程，保留原数据目录副本；将database.sqlite3和blobs目录解压到新的空数据目录；设置BID_DATA_DIR指向该目录，再启动。禁止运行时覆盖数据库，不混入旧wal/shm。"}
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            db_raw = path.read_bytes()
            archive.writestr("database.sqlite3", db_raw)
            manifest["database_sha256"] = hashlib.sha256(db_raw).hexdigest()
            for file in files:
                raw = blob_bytes(store, file)
                archive.writestr("blobs/" + file["id"], raw)
                manifest["files"].append({"id": file["id"], "sha256": file["sha256"], "size": len(raw)})
            archive.writestr("backup_manifest.json", dumps(manifest).encode("utf-8"))
        raw = output.getvalue()
        backup_id = uid()
        with open(store.blobs / backup_id, "xb") as f:
            f.write(raw)
        with store.transaction() as c:
            item = store.save(c, "backup", {"id": backup_id, "name": "local_backup.zip", "size": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(), "download_url": f"/api/backups/{backup_id}/download", "manifest": manifest})
        return {"item": item}


@router.get("/backups/{backup_id}/download")
def backup_download(backup_id: str, request: Request):
    store = request.app.state.store
    with store.transaction() as c:
        backup = store.get(c, "backup", backup_id)
        raw = blob_bytes(store, backup)
    return Response(raw, media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="local_backup.zip"', "X-Content-SHA256": backup["sha256"]})
