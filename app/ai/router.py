"""AI辅助路由（Phase 1只读辅助）。

端点：
- GET  /api/ai/config      读取配置（api_key掩码）
- PUT  /api/ai/config      更新配置（expected_version乐观锁）
- POST /api/ai/test        测试连接（探活/models）
- POST /api/ai/preview     预览脱敏内容并创建一次性preview令牌（第一道闸）
- POST /api/ai/invoke      确认并调用AI（第二道闸：user_confirmed + 一次性令牌）
- GET  /api/ai/calls       审计日志列表（剥离重字段）
- GET  /api/ai/calls/{id}  审计日志详情

事务纪律：配置/项目读取在 Store.transaction() 内完成并关闭事务后，才发起AI网络调用；
审计写入走独立短连接（audit_connection），不进入全局写锁。
"""
from __future__ import annotations

import asyncio
import base64
import time
from urllib.parse import urlparse

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from ..core import DomainError, Store
from ..schemas import AIConfigUpdate, AIInvokeRequest, AIPreviewRequest
from .audit import audit_connection, daily_token_usage, get_ai_call, log_ai_call, query_ai_calls
from .guard import GuardError, check_ai_enabled, consume_preview_token, create_preview_token
from .provider import (AIDisabledError, AIProviderError, AIRequest, build_provider,
                       feature_timeout)
from .redactor import estimate_tokens, redact_text

ai_router = APIRouter(prefix="/api/ai", tags=["AI辅助"])

# 默认串行；Phase 1不做并发放大，避免本机推理资源争抢。
_ai_semaphore = asyncio.Semaphore(1)

MAX_PROMPT_CHARS = 120000  # 发送前正文截断上限
DISPLAY_CHARS = 20000  # 预览回显上限
DISCLAIMER = ("AI生成内容仅为辅助建议，须经企业人工核对确认后方可使用；"
              "本软件不代替人工判断，不对AI输出真实性负责。")
_ENC_PREFIX = "enc:v1:"


def _new_default() -> dict:
    """未配置时的默认AI设置：禁用 + NullProvider，不影响现有本地规则流程。"""
    return {
        "id": "default", "enabled": False, "provider": "null",
        "base_url": "http://127.0.0.1:11434/v1", "model": "qwen2.5:7b-instruct",
        "embedding_model": "bge-m3", "api_key": "", "is_cloud": False,
        "redaction_level": "standard", "default_scope": ["documents"],
        "max_concurrent": 1, "daily_token_budget": 200000, "timeout_seconds": 120.0,
    }


def _encode_key(plain: str) -> str:
    """本机SQLite已是物理隔离，采用base64+前缀标记的轻量编码，避免明文直存。"""
    if not plain:
        return ""
    return _ENC_PREFIX + base64.b64encode(plain.encode()).decode()


def _decode_key(stored: str) -> str:
    if not stored:
        return ""
    if stored.startswith(_ENC_PREFIX):
        try:
            return base64.b64decode(stored[len(_ENC_PREFIX):].encode()).decode()
        except Exception:
            return ""
    return stored  # 兼容历史明文


def _mask_key(stored: str) -> str:
    plain = _decode_key(stored)
    return ("****" + plain[-4:]) if plain else ""


def _mask_endpoint(url: str) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.hostname}" if parsed.hostname else url


def _config_out(config: dict) -> dict:
    return {
        "id": config["id"], "version": config["version"],
        "created_at": config["created_at"], "updated_at": config["updated_at"],
        "enabled": config["enabled"], "provider": config["provider"],
        "base_url": config.get("base_url", ""), "model": config.get("model", ""),
        "embedding_model": config.get("embedding_model", ""),
        "api_key_masked": _mask_key(config.get("api_key", "")),
        "is_cloud": config.get("is_cloud", False),
        "redaction_level": config.get("redaction_level", "standard"),
        "default_scope": config.get("default_scope", ["documents"]),
        "max_concurrent": config.get("max_concurrent", 1),
        "daily_token_budget": config.get("daily_token_budget", 200000),
        "timeout_seconds": config.get("timeout_seconds", 120.0),
        "external_ai": bool(config.get("enabled") and config.get("provider", "null") != "null"),
    }


def _ensure_config_tx(c, store) -> dict:
    """事务内读取ai_config单例，不存在则以默认值创建（幂等）。"""
    config = store.get(c, "ai_config", "default", False)
    if config is None:
        config = store.save(c, "ai_config", _new_default(), "init")
    return config


def _read_config(store) -> dict:
    """只读获取配置（供异步端点在事务外调用）；未持久化时返回内存默认值。"""
    with store.transaction() as c:
        config = store.get(c, "ai_config", "default", False)
    return config or _new_default()


def _guard_domain(err: GuardError) -> DomainError:
    return DomainError(err.code, err.message, err.status_code)


def _collect_scope(c, store, p: dict, scope) -> tuple[str, list[str], list[str], list[str], list[str], list[str]]:
    """在事务内组装待发送正文与脱敏词典；不调用任何AI。"""
    warnings: list[str] = []
    scope_applied: list[str] = []
    docs = store.all(c, "document", p["id"])
    # 仅取每个来源族的最新版本，避免把已被补遗替代的旧正文发给AI
    latest: dict[str, dict] = {}
    for d in docs:
        fam = d.get("source_family_id")
        if fam not in latest or d.get("source_version", 0) > latest[fam].get("source_version", 0):
            latest[fam] = d
    current = list(latest.values())
    if scope.document_ids:
        wanted = set(scope.document_ids)
        current = [d for d in current if d["id"] in wanted]
        scope_applied.append("documents:selected")
    else:
        scope_applied.append("documents:all_current")

    parts: list[str] = []
    if scope.include_documents:
        for d in sorted(current, key=lambda x: x.get("source_version", 0)):
            if d.get("parse_status") != "parsed":
                warnings.append(f"《{d['title']}》未完成解析，未纳入摘要正文")
                continue
            block_texts = [b["text"] for b in d.get("blocks", []) if b.get("text")]
            if block_texts:
                parts.append(f"## {d['title']}\n" + "\n".join(block_texts))
    text = "\n\n".join(parts)

    if scope.include_facts:
        scope_applied.append("facts")
        fact_lines = [f"{k}: {v.get('value', '')}" for k, v in p.get("facts", {}).items()]
        if fact_lines:
            text = (text + "\n\n## 项目事实\n" + "\n".join(fact_lines)) if text else "\n".join(fact_lines)

    if not text.strip():
        raise DomainError("NO_CONTENT", "所选范围内没有可用于摘要的招标文件正文，请先上传或人工摘录", 422)

    if len(text) > MAX_PROMPT_CHARS:
        text = text[:MAX_PROMPT_CHARS]
        warnings.append(f"正文超过{MAX_PROMPT_CHARS}字符，已截断后再脱敏发送")
        scope_applied.append("truncated")

    company = [p["client"]] if p.get("client") else []
    project_names = [p["name"]] if p.get("name") else []
    person: list[str] = []
    return text, scope_applied, warnings, company, person, project_names


def _build_messages(feature: str, redacted_text: str) -> list[dict]:
    if feature == "summarize":
        system = ("你是投标文档分析助手。请基于用户提供的招标文件正文，输出结构化摘要，依次覆盖："
                  "项目概况、关键资格要求、强制性条款（废标/否决项）、评分要点、交付与工期要求、"
                  "需人工重点核对的风险点。只依据所提供内容，不得编造；对脱敏占位符"
                  "（如[甲方A]、[金额:100万-500万]）保持原样，不要猜测真实值。用中文分条列出。")
        user = f"以下是招标文件正文（已脱敏）：\n\n{redacted_text}\n\n请输出智能摘要。"
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]
    raise DomainError("AI_FEATURE_UNSUPPORTED", f"暂不支持的AI功能: {feature}", 422)


def _fallback_result(token, config: dict, code: str, message: str) -> dict:
    return {
        "status": "fallback", "feature": token.feature,
        "provider": config.get("provider", "null"), "model": config.get("model", ""),
        "text": "", "origin": "rule_engine", "latency_ms": 0,
        "prompt_tokens": 0, "completion_tokens": 0, "finish_reason": "error",
        "degradation": {"to": "rule_engine", "code": code, "message": message},
        "disclaimer": DISCLAIMER,
    }


async def _run_ai(provider, token, config: dict) -> dict:
    """事务外发起AI调用；失败/超时/禁用一律降级为fallback，不抛给前端。"""
    if provider.name == "null":
        return _fallback_result(token, config, "AI_DISABLED", "外部AI未启用，已降级为本地规则占位结果")
    payload = token.redacted_payload
    req = AIRequest(feature=token.feature, messages=payload["messages"],
                    max_tokens=payload["max_tokens"], temperature=payload["temperature"])
    timeout = feature_timeout(float(config.get("timeout_seconds", 120.0)), token.feature)
    try:
        async with _ai_semaphore:
            resp = await asyncio.wait_for(provider.chat(req), timeout=timeout)
    except AIDisabledError as e:
        return _fallback_result(token, config, e.code, e.message)
    except AIProviderError as e:
        return _fallback_result(token, config, e.code, e.message)
    except asyncio.TimeoutError:
        return _fallback_result(token, config, "AI_TIMEOUT", f"AI推理超时（{timeout:g}s），已降级")
    return {
        "status": "success", "feature": token.feature, "provider": resp.provider,
        "model": resp.model, "text": resp.text, "origin": "ai_suggestion",
        "latency_ms": resp.latency_ms, "prompt_tokens": resp.prompt_tokens,
        "completion_tokens": resp.completion_tokens, "finish_reason": resp.finish_reason,
        "degradation": None, "disclaimer": DISCLAIMER,
    }


def _write_audit(store, token, config: dict, result: dict) -> int:
    degradation = result.get("degradation") or {}
    with audit_connection(store.path) as conn:
        return log_ai_call(
            conn, project_id=token.project_id, entity_kind="project", entity_id=token.project_id,
            phase=1, feature=token.feature, provider=result.get("provider", "null"),
            model=result.get("model") or None, endpoint_masked=_mask_endpoint(config.get("base_url", "")),
            prompt_text=token.redacted_payload.get("prompt_text"), prompt_tokens=result.get("prompt_tokens", 0),
            response_text=result.get("text") or None, response_tokens=result.get("completion_tokens", 0),
            redaction_summary=token.redaction_summary, scope_applied=token.scope_applied,
            user_confirmed=True, latency_ms=result.get("latency_ms", 0),
            status=result.get("status", "success"), error_code=degradation.get("code"),
            fallback_used=result.get("status") == "fallback",
        )


def _daily_usage(store) -> int:
    with audit_connection(store.path) as conn:
        return daily_token_usage(conn)


def _summary(record: dict) -> dict:
    """列表摘要：剥离prompt_preview/response_preview重字段。"""
    return {k: v for k, v in record.items() if k not in ("prompt_preview", "response_preview")}


@ai_router.get("/config")
def ai_config_get(request: Request):
    store = request.app.state.store
    with store.transaction() as c:
        config = _ensure_config_tx(c, store)
    return {"item": _config_out(config)}


@ai_router.put("/config")
def ai_config_update(body: AIConfigUpdate, request: Request):
    store = request.app.state.store
    with store.transaction() as c:
        config = _ensure_config_tx(c, store)
        Store.expect(config, body.expected_version)
        updates = body.model_dump(mode="json",
                                  exclude={"expected_version", "api_key", "base_url", "model", "embedding_model"})
        config.update(updates)
        # 空字符串表示不修改，保留原值
        if body.base_url.strip():
            config["base_url"] = body.base_url.strip()
        if body.model.strip():
            config["model"] = body.model.strip()
        if body.embedding_model.strip():
            config["embedding_model"] = body.embedding_model.strip()
        # api_key为None或含*（掩码回显）时保留原密钥
        if body.api_key is not None and "*" not in body.api_key:
            config["api_key"] = _encode_key(body.api_key)
        config = store.save(c, "ai_config", config, "config_update")
        return {"item": _config_out(config)}


@ai_router.post("/test")
async def ai_test(request: Request):
    store = request.app.state.store
    config = await run_in_threadpool(_read_config, store)
    if not config.get("enabled") or config.get("provider", "null") == "null":
        return {"item": {"reachable": False, "reason": "AI未启用", "models": [],
                         "provider": config.get("provider", "null"), "model": config.get("model", ""),
                         "latency_ms": 0, "base_url": config.get("base_url", "")}}
    try:
        provider = build_provider(config, _decode_key(config.get("api_key", "")))
    except AIProviderError as e:
        raise DomainError(e.code, e.message, 422)
    start = time.perf_counter()
    try:
        health = await provider.health()
    finally:
        await provider.close()
    latency = int((time.perf_counter() - start) * 1000)
    reachable = health.get("status") == "ok"
    return {"item": {"reachable": reachable, "models": health.get("models", []),
                     "provider": config.get("provider", "null"), "model": config.get("model", ""),
                     "latency_ms": latency, "base_url": config.get("base_url", ""),
                     "reason": "" if reachable else (health.get("error") or "连接失败")}}


@ai_router.post("/preview")
def ai_preview(body: AIPreviewRequest, request: Request):
    store = request.app.state.store
    # 第一道闸：配置级授权（读配置在事务内，闸门判定在事务外）
    with store.transaction() as c:
        config = _ensure_config_tx(c, store)
    try:
        check_ai_enabled(config)
    except GuardError as e:
        raise _guard_domain(e)

    # 事务内读项目与来源正文→关事务
    with store.transaction() as c:
        p = store.project(c, body.project_id)
        text, scope_applied, warnings, company, person, project_names = _collect_scope(c, store, p, body.scope)

    # 脱敏与token估算为纯CPU操作，事务外执行
    level = config.get("redaction_level", "standard")
    red = redact_text(text, company_names=company, person_names=person,
                      project_names=project_names, level=level)
    estimated = estimate_tokens(red.text)
    messages = _build_messages(body.feature, red.text)
    payload = {"messages": messages, "max_tokens": 2048, "temperature": 0.2, "prompt_text": red.text}

    token = create_preview_token(
        feature=body.feature, project_id=p["id"], project_version=p["version"],
        redacted_payload=payload, redaction_summary=red.summary,
        estimated_tokens=estimated, scope_applied=scope_applied,
    )
    display = red.text[:DISPLAY_CHARS]
    if len(red.text) > DISPLAY_CHARS:
        warnings.append(f"预览仅回显前{DISPLAY_CHARS}字符，实际发送已按脱敏后全文计")
    return {"item": {
        "preview_id": token.preview_id, "feature": body.feature, "project_id": p["id"],
        "project_version": p["version"], "provider": config.get("provider", "null"),
        "model": config.get("model", ""), "redaction_level": level,
        "redaction_summary": red.summary, "masked_tokens": red.masked_tokens,
        "estimated_tokens": estimated, "scope_applied": scope_applied,
        "redacted_text": display, "warnings": warnings,
        "expires_in_seconds": 300, "disclaimer": DISCLAIMER,
    }}


@ai_router.post("/invoke")
async def ai_invoke(body: AIInvokeRequest, request: Request):
    store = request.app.state.store
    # 第二道闸：调用级授权，必须明确确认
    if not body.user_confirmed:
        raise DomainError("CONFIRMATION_REQUIRED", "调用AI前必须确认已核对脱敏预览内容", 422)
    try:
        token = consume_preview_token(body.preview_id)
    except GuardError as e:
        raise _guard_domain(e)

    config = await run_in_threadpool(_read_config, store)

    # 每日token预算闸门（0表示不限）
    budget = int(config.get("daily_token_budget", 0) or 0)
    if budget > 0:
        used = await run_in_threadpool(_daily_usage, store)
        if used + token.estimated_tokens > budget:
            result = _fallback_result(token, config, "AI_BUDGET_EXCEEDED",
                                      f"预计超出每日token预算（已用{used}），已降级为本地规则")
            call_id = await run_in_threadpool(_write_audit, store, token, config, result)
            result["call_id"] = call_id
            return {"item": result}

    try:
        provider = build_provider(config, _decode_key(config.get("api_key", "")))
    except AIProviderError as e:
        result = _fallback_result(token, config, e.code, e.message)
        call_id = await run_in_threadpool(_write_audit, store, token, config, result)
        result["call_id"] = call_id
        return {"item": result}

    # AI调用在事务外；完成后关闭客户端
    try:
        result = await _run_ai(provider, token, config)
    finally:
        await provider.close()

    call_id = await run_in_threadpool(_write_audit, store, token, config, result)
    result["call_id"] = call_id
    return {"item": result}


@ai_router.get("/calls")
def ai_calls(request: Request, project_id: str | None = None, limit: int = 50, offset: int = 0):
    store = request.app.state.store
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    with audit_connection(store.path) as conn:
        records, total = query_ai_calls(conn, project_id=project_id, limit=limit, offset=offset)
    return {"items": [_summary(r) for r in records], "total": total}


@ai_router.get("/calls/{call_id}")
def ai_call_detail(call_id: int, request: Request):
    store = request.app.state.store
    with audit_connection(store.path) as conn:
        record = get_ai_call(conn, call_id)
    if record is None:
        raise DomainError("NOT_FOUND", "审计记录不存在", 404)
    return {"item": record}
