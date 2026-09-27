"""FastAPI工厂：同源本机API与独立前端静态入口。"""
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from .core import ROOT, DomainError, Settings, Store
from .demo import load_demo
from .files import blob_bytes, file_summary, parse_and_store, read_upload
from .resources import seed_templates
from .schemas import DemoLoad, ErrorResponse
from .security import LocalSecurityMiddleware
from . import projects, resources, pricing, drafts, review, exports
from .ai import ai_router

HELP = [
    {"title": "本地试用边界", "text": "本程序仅在127.0.0.1监听，单机内部试用，无真实登录。外部AI未接入；生成使用本地规则、模板及已确认事实，不是云模型结果。不联网OCR，不加载外部字体、CDN或遥测。"},
    {"title": "推荐操作顺序", "text": "新建监理或TIS项目→上传招标文件或人工摘录→确认候选需求及事实→选择模板和企业资料→填写报价并确认税率→生成草稿→逐章编辑并关联响应和证明→风险检查→技术、商务、资质分别记录意见→人工确认冻结→导出。"},
    {"title": "文件与来源", "text": "支持不超过20MB的DOCX与文字PDF；不支持DOC、宏及加密文件。PDF最多300页，隔离解析25秒；扫描件无OCR，请人工摘录。PDF定位页码，Word定位段落和表格而不猜测页码。补遗保存为新的来源版本，原件及哈希留存。"},
    {"title": "资料与版本", "text": "企业资质、人员、业绩须自行核验原件、有效期及适用范围。审核通过仅为人工记录，不代表软件判真。内置模板先复制再编辑；历史素材先上传原件再选择内容块。来源变化会使关联项目复核失效。"},
    {"title": "事实键与行业边界", "text": "事实填写value、confirmed和source。模板使用staffing、control_points、deliverables、regional_rules、payment_terms、commercial_terms；TIS另需commission_relationship、independence、inspection_nodes、risk_process。source_completeness用于记录无文字或低质量来源的人工完整性核对。TIS不代替监理、法定检测或保险核保理赔，地区规则不能全国套用。"},
    {"title": "报价", "text": "金额均为十进制字符串；数量最多3位小数，单价2位，税率用0至1的小数并明确确认。逐行四舍五入至分，再合计、计算税额及总额。监理费、TIS技术服务费与保险保费不得混写，首期不测算保费。"},
    {"title": "草稿与覆盖保护", "text": "再次生成须明确确认，旧稿只读且永久保留。编辑保存版本冲突时请刷新，不要盲目重试覆盖。资料或需求变化后，可以重新生成，或逐章人工核对并同步输入快照；报价变化必须重新生成，避免正文与表格不同步。"},
    {"title": "复核与导出", "text": "阻断风险不允许标记已内部复核，但可导出带缺项清单的送审稿。技术、商务、资质须有同一当前内容版本的通过意见并人工确认。已复核版使用不可变冻结快照，修改后复核失效。ZIP保留原始附件，不修改签章。Word/WPS实际分页及打印排版仍须企业人工确认。"},
    {"title": "备份与恢复", "text": "备份使用SQLite一致性快照并核对全部附件哈希。恢复必须停机：保存原数据目录副本，将ZIP中的database.sqlite3与blobs解压到新的空目录，设置BID_DATA_DIR，再启动。不要在线覆盖数据库，不混入旧wal/shm文件。备份包含项目和企业资料，请妥善保管。"},
    {"title": "数据隐私", "text": "数据留在本机，但不等于磁盘加密。系统账户、磁盘权限与备份介质由企业管理。删除项目仅移除项目入口，历史修订与证据仍保留；不进行自动投标、电子签署或门户提交。首次安装Python依赖需要联网下载，正常运行不依赖云服务。"},
]


def create_app(settings: Settings | None = None):
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app):
        app.state.store = Store(settings)
        seed_templates(app.state.store)
        yield

    app = FastAPI(title="本地智能投标辅助软件", version="1.0.0", lifespan=lifespan,
        docs_url=None, redoc_url=None, openapi_url="/api/openapi.json",
        description="仅127.0.0.1本机同源。状态变更必须携带Origin。所有时间含时区、金额为十进制字符串；未知输入字段拒绝。",
        responses={status: {"model": ErrorResponse} for status in (400, 403, 404, 409, 413, 415, 422, 500, 503)})
    app.state.settings = settings
    app.add_middleware(LocalSecurityMiddleware, settings=settings)

    @app.exception_handler(DomainError)
    async def domain_error(request, exc):
        return JSONResponse({"code": exc.code, "message": exc.message}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        locations = [".".join(str(x) for x in e["loc"]) for e in exc.errors()[:8]]
        return JSONResponse({"code": "VALIDATION_ERROR", "message": "请求字段不符合接口约束：" + "、".join(locations)}, status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        messages = {404: "接口或文件不存在", 405: "请求方法不支持", 400: "请求内容或上传格式无效"}
        return JSONResponse({"code": f"HTTP_{exc.status_code}", "message": messages.get(exc.status_code, "请求未成功")}, status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        # 不向前端返回内部路径、堆栈或异常原文。
        return JSONResponse({"code": "INTERNAL_ERROR", "message": "本地操作失败，请确认磁盘空间与数据目录权限，必要时联系维护人员"},
                            status_code=500, headers=LocalSecurityMiddleware(None, settings).headers)

    for router in (projects.router, resources.router, pricing.router, drafts.router, review.router, exports.router):
        app.include_router(router)
    app.include_router(ai_router)

    @app.get("/api/health", tags=["设置与健康"])
    def health(request: Request):
        store = request.app.state.store
        with store.transaction() as c:
            schema = c.execute("PRAGMA user_version").fetchone()[0]
            config = store.get(c, "ai_config", "default", False)
        external_ai = bool(config and config.get("enabled") and config.get("provider", "null") != "null")
        ai_mode = config.get("provider") if external_ai else "local_rules"
        return {"status": "ok", "version": "1.0.0", "schema_version": schema, "ai_mode": ai_mode, "external_ai": external_ai}

    @app.get("/api/dashboard", tags=["设置与健康"])
    def dashboard(request: Request):
        store = request.app.state.store
        with store.transaction() as c:
            items = store.all(c, "project")
            return {"projects": len(items), "active": sum(not x["archived"] for x in items),
                "archived": sum(x["archived"] for x in items), "reviewed": sum(x["review_status"] == "reviewed" for x in items),
                "demo": sum(x.get("is_demo", False) for x in items), "materials": len(store.all(c, "material")),
                "templates": len(store.all(c, "template")), "snippets": len(store.all(c, "snippet"))}

    @app.get("/api/settings", tags=["设置与健康"])
    def get_settings(request: Request):
        store = request.app.state.store
        with store.transaction() as c:
            config = store.get(c, "ai_config", "default", False)
        external_ai = bool(config and config.get("enabled") and config.get("provider", "null") != "null")
        return {"data_directory": str(settings.data_dir), "host": "127.0.0.1", "port": settings.port,
            "max_upload_bytes": settings.max_upload, "max_pdf_pages": settings.max_pdf_pages,
            "parse_timeout_seconds": settings.parse_timeout, "external_ai": external_ai, "cloud_ocr": False,
            "telemetry": False, "authentication": "none_local_records_only", "schema_version": 1,
            "privacy_notice": HELP[-1]["text"], "restore_instructions": HELP[-2]["text"]}

    @app.get("/api/help", tags=["设置与健康"])
    def help_content():
        return {"items": HELP}

    @app.post("/api/demo/load", tags=["设置与健康"])
    def demo(body: DemoLoad, request: Request):
        if not body.confirmation:
            raise DomainError("CONFIRMATION_REQUIRED", "请确认载入明确标注的虚构演示资料", 422)
        return load_demo(request.app.state.store)

    @app.get("/api/files", tags=["受控文件"])
    def list_files(request: Request, purpose: str | None = None):
        store = request.app.state.store
        with store.transaction() as c:
            items = store.all(c, "file")
        # 列表剥离 blocks 解析正文；完整内容通过 GET /api/files/{file_id} 获取。
        return {"items": [file_summary(x) for x in items if not purpose or x["purpose"] == purpose]}

    @app.post("/api/files", status_code=201, tags=["受控文件"])
    async def upload_file(request: Request, file: UploadFile = File(...)):
        # 异步端点仅做流式读取；阻塞解析与事务已放入线程池，不阻塞事件循环。
        store = request.app.state.store
        name, extension, raw = await read_upload(file, settings)
        item = await run_in_threadpool(parse_and_store, store, name, extension, raw, "attachment_or_history")
        return {"item": item}

    @app.get("/api/files/{file_id}", tags=["受控文件"])
    def file_metadata(file_id: str, request: Request):
        with request.app.state.store.transaction() as c:
            return {"item": request.app.state.store.get(c, "file", file_id)}

    @app.get("/api/files/{file_id}/download", tags=["受控文件"])
    def file_download(file_id: str, request: Request):
        store = request.app.state.store
        with store.transaction() as c:
            file = store.get(c, "file", file_id)
            raw = blob_bytes(store, file)
        return Response(raw, media_type=file["media_type"], headers={
            "Content-Disposition": "attachment; filename=download; filename*=UTF-8''" + quote(file["name"], safe=""),
            "X-Content-SHA256": file["sha256"]})

    @app.get("/api/projects/{project_id}/events", tags=["项目与招标分析"])
    def project_events(project_id: str, request: Request):
        store = request.app.state.store
        with store.transaction() as c:
            store.project(c, project_id)
            rows = c.execute("SELECT id,at,action,entity_id,project_id FROM events WHERE project_id=? OR entity_id=? ORDER BY id DESC LIMIT 500", (project_id, project_id))
            return {"items": [dict(row) for row in rows]}

    @app.get("/", include_in_schema=False)
    def index():
        path = ROOT / "app" / "static" / "index.html"
        if path.is_file():
            return FileResponse(path)
        return JSONResponse({"code": "FRONTEND_PENDING", "message": "后端已安装，前端由独立工程师接入；API契约位于/api/openapi.json"})

    static_directory = ROOT / "app" / "static"
    if static_directory.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_directory)), name="static")
    from .contract import attach_response_contract
    attach_response_contract(app)
    return app
