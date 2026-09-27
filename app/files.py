"""受控附件与Windows spawn隔离解析；上传名只用作显示标签。"""
from __future__ import annotations

import hashlib
import io
import multiprocessing as mp
import re
import zipfile
from pathlib import PurePosixPath

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader

from .core import DomainError, uid

MAX_TEXT = 2_000_000
# 列表只返回元数据摘要；blocks 等解析正文体积巨大，仅通过 GET /api/files/{id} 获取。
FILE_SUMMARY_KEYS = ("id", "project_id", "version", "created_at", "updated_at", "name", "sha256",
                     "size", "media_type", "purpose", "download_url", "parse_status",
                     "page_count", "warnings", "kind")


def file_summary(file):
    return {key: file[key] for key in FILE_SUMMARY_KEYS if key in file}


def safe_name(name: str) -> str:
    name = (name or "未命名").replace("\\", "/").split("/")[-1]
    name = re.sub(r'[\x00-\x1f<>:"|?*]', "_", name).strip(" .")
    return name[:150] or "未命名"


def _docx_blocks(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos = archive.infolist()
        if len(infos) > 2000:
            raise DomainError("ZIP_LIMIT", "DOCX成员数量过多")
        total = 0
        names = set()
        for member in infos:
            name = member.filename.replace("\\", "/")
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or ":" in name or "\x00" in name:
                raise DomainError("UNSAFE_ARCHIVE", "DOCX包含不安全的成员路径")
            if name in names:
                raise DomainError("UNSAFE_ARCHIVE", "DOCX包含重复成员")
            names.add(name)
            if member.flag_bits & 1:
                raise DomainError("ENCRYPTED_FILE", "不支持加密文档")
            if "vbaproject" in name.lower() or name.lower().startswith(("word/activex/", "word/embeddings/")):
                raise DomainError("MACRO_FILE", "不支持宏、ActiveX或嵌入式可执行内容")
            total += member.file_size
            if total > 80 * 1024 * 1024 or member.file_size > 25 * 1024 * 1024:
                raise DomainError("ZIP_LIMIT", "DOCX解压大小超出安全限制")
            if member.file_size > 1024 * 1024 and member.file_size / max(member.compress_size, 1) > 150:
                raise DomainError("ZIP_LIMIT", "DOCX压缩比例异常")
            if name.endswith((".xml", ".rels")):
                xml = archive.read(member)
                if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
                    raise DomainError("UNSAFE_XML", "DOCX不允许外部实体或DTD")
        if "word/document.xml" not in names or "[Content_Types].xml" not in names:
            raise DomainError("INVALID_DOCX", "不是有效DOCX文件")
        if b"macroEnabled" in archive.read("[Content_Types].xml"):
            raise DomainError("MACRO_FILE", "不支持启用宏的文档")
    doc = Document(io.BytesIO(raw))
    blocks = []
    total_text = 0
    paragraph, table = 0, 0
    for element in doc.element.body.iterchildren():
        if element.tag == qn("w:p"):
            paragraph += 1
            text = Paragraph(element, doc).text.strip()
            if text:
                total_text += len(text)
                blocks.append({"id": uid(), "text": text, "locator": {"kind": "paragraph", "paragraph": paragraph}})
        elif element.tag == qn("w:tbl"):
            table += 1
            for row_index, row in enumerate(Table(element, doc).rows, 1):
                text = " | ".join(cell.text.strip() for cell in row.cells).strip(" |")
                if text:
                    total_text += len(text)
                    blocks.append({"id": uid(), "text": text, "locator": {"kind": "table", "table": table, "row": row_index}})
        if len(blocks) > 15000 or total_text > MAX_TEXT:
            raise DomainError("TEXT_LIMIT", "文档文本规模超出限制")
    return blocks, None


def _pdf_blocks(raw, max_pages):
    reader = PdfReader(io.BytesIO(raw), strict=True)
    if reader.is_encrypted:
        raise DomainError("ENCRYPTED_FILE", "不支持加密PDF，请提供未加密原件或人工摘录")
    if len(reader.pages) > max_pages:
        raise DomainError("PDF_PAGE_LIMIT", f"PDF最多允许{max_pages}页，请拆分后上传")
    blocks = []
    total = 0
    for page_no, page in enumerate(reader.pages, 1):
        text = (page.extract_text() or "").strip()
        total += len(text)
        if total > MAX_TEXT:
            raise DomainError("TEXT_LIMIT", "文档文本规模超出限制")
        if text:
            blocks.append({"id": uid(), "text": text, "locator": {"kind": "page", "page": page_no}})
    return blocks, len(reader.pages)


def _parse_worker(path, extension, max_pages, output):
    try:
        with open(path, "rb") as f:
            raw = f.read(20 * 1024 * 1024 + 1)
        if extension == ".docx":
            blocks, pages = _docx_blocks(raw)
        else:
            blocks, pages = _pdf_blocks(raw, max_pages)
        text = "".join(b["text"] for b in blocks)
        if len(text) > MAX_TEXT:
            raise DomainError("TEXT_LIMIT", "文档文本规模超出限制")
        meaningful = sum(ch.isalnum() for ch in text)
        status = "parsed" if meaningful >= 5 else "needs_manual_excerpt"
        warnings = []
        if extension == ".docx":
            warnings.append("DOCX仅提取正文段落和表格；页眉页脚、图片、文本框及批注等内容请对照原件人工核对，不推断Word页码。")
        if status != "parsed":
            warnings.append("未提取到足够文字，可能是扫描件或空白文件。未进行OCR，请使用人工摘录入口。")
        elif text.count("\ufffd") > max(5, len(text) // 20):
            status = "low_quality"
            warnings.append("文本编码质量较低，请核对原件并人工摘录，不应直接采信提取结果。")
        if extension == ".pdf" and pages and len(blocks) < pages:
            warnings.append("部分PDF页未提取到文字，可能包含扫描页面，请逐页核对。")
        output.send({"blocks": blocks, "page_count": pages, "parse_status": status, "warnings": warnings})
    except DomainError as exc:
        output.send({"error": exc.code, "message": exc.message})
    except BaseException:
        output.send({"error": "INVALID_DOCUMENT", "message": "文件损坏、格式不符或无法解析，请更换DOCX/文字PDF，或人工摘录"})
    finally:
        output.close()


def parse_isolated(path, extension, settings):
    context = mp.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    worker = context.Process(target=_parse_worker, args=(str(path), extension, settings.max_pdf_pages, sender), daemon=True)
    worker.start()
    sender.close()
    try:
        if not receiver.poll(settings.parse_timeout):
            raise DomainError("PARSE_TIMEOUT", "解析超时，请拆分文件或人工摘录", 422)
        try:
            result = receiver.recv()
        except EOFError:
            raise DomainError("PARSE_FAILED", "隔离解析进程终止，请更换文件或人工摘录", 422)
        if "error" in result:
            raise DomainError(result["error"], result["message"], 422)
        return result
    finally:
        receiver.close()
        worker.join(timeout=0.5)
        if worker.is_alive():
            worker.terminate()
            worker.join(timeout=2)
        worker.close()


def upload_target(upload):
    name = safe_name(upload.filename)
    extension = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if extension not in (".docx", ".pdf"):
        raise DomainError("UNSUPPORTED_FILE", "仅支持DOCX和文字PDF；不支持DOC、宏、加密文件或图片OCR", 415)
    return name, extension


def verify_upload(name, extension, raw, settings):
    if len(raw) > settings.max_upload:
        raise DomainError("FILE_TOO_LARGE", "单个上传文件不得超过20MB", 413)
    if not raw:
        raise DomainError("EMPTY_FILE", "上传文件为空", 422)
    if extension == ".pdf" and not raw.startswith(b"%PDF-"):
        raise DomainError("INVALID_DOCUMENT", "PDF文件签名与扩展名不符", 422)
    if extension == ".docx" and not raw.startswith(b"PK\x03\x04"):
        raise DomainError("INVALID_DOCUMENT", "DOCX文件签名与扩展名不符，可能是加密或旧格式", 422)
    return name, extension, raw


async def read_upload(upload, settings):
    name, extension = upload_target(upload)
    chunks, size = [], 0
    while chunk := await upload.read(1024 * 1024):
        size += len(chunk)
        if size > settings.max_upload:
            raise DomainError("FILE_TOO_LARGE", "单个上传文件不得超过20MB", 413)
        chunks.append(chunk)
    return verify_upload(name, extension, b"".join(chunks), settings)


def read_upload_sync(upload, settings):
    """同步读取已落盘的上传体，供同步端点在线程池中使用，不阻塞事件循环。"""
    name, extension = upload_target(upload)
    upload.file.seek(0)
    raw = upload.file.read(settings.max_upload + 1)
    return verify_upload(name, extension, raw, settings)


def store_blob(store, c, raw, name, media_type, parsed=None, purpose="attachment"):
    file_id = uid()
    with open(store.blobs / file_id, "xb") as output:
        output.write(raw)
    data = {"id": file_id, "name": safe_name(name), "sha256": hashlib.sha256(raw).hexdigest(),
            "size": len(raw), "media_type": media_type, "purpose": purpose,
            "download_url": f"/api/files/{file_id}/download"}
    if parsed:
        data.update(parsed)
    return store.save(c, "file", data)


def parse_and_store(store, name, extension, raw, purpose="attachment"):
    temporary_id = uid()
    path = store.blobs / temporary_id
    with open(path, "xb") as output:
        output.write(raw)
    try:
        parsed = parse_isolated(path, extension, store.settings)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    # 文件从始至终使用内部ID；未登记的事务回滚文件不会进入下载或备份。
    with store.transaction() as c:
        file_id = temporary_id
        media = "application/pdf" if extension == ".pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        file = store.save(c, "file", {"id": file_id, "name": name, "sha256": hashlib.sha256(raw).hexdigest(),
            "size": len(raw), "media_type": media, "purpose": purpose,
            "download_url": f"/api/files/{file_id}/download", **parsed})
        return file


def blob_bytes(store, file):
    path = store.blobs / file["id"]
    try:
        raw = path.read_bytes()
    except OSError:
        raise DomainError("ATTACHMENT_MISSING", "附件不存在，请从备份恢复或重新上传", 409)
    if hashlib.sha256(raw).hexdigest() != file["sha256"]:
        raise DomainError("ATTACHMENT_HASH_MISMATCH", "附件哈希不一致，请核对本地文件完整性", 409)
    return raw
