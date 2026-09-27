"""AI调用审计日志：ai_calls表DDL + 写入/查询/保留策略。

存储位置：与业务库同一 database.sqlite3，但独立于 Store.transaction() 全局写锁，
使用短生命周期连接（WAL模式下写者互斥由 busy_timeout 兜底），避免AI审计阻塞业务事务。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

# ai_calls表DDL
AI_CALLS_DDL = """
CREATE TABLE IF NOT EXISTS ai_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    project_id TEXT,
    entity_kind TEXT,
    entity_id TEXT,
    phase INTEGER DEFAULT 1,
    feature TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT,
    endpoint_masked TEXT,
    prompt_hash TEXT,
    prompt_preview TEXT,
    prompt_tokens INTEGER DEFAULT 0,
    response_hash TEXT,
    response_preview TEXT,
    response_tokens INTEGER DEFAULT 0,
    redaction_summary TEXT,
    scope_applied TEXT,
    user_confirmed INTEGER DEFAULT 0,
    confirmation_at TEXT,
    latency_ms INTEGER DEFAULT 0,
    status TEXT NOT NULL,
    error_code TEXT,
    fallback_used INTEGER DEFAULT 0,
    origin_mark TEXT DEFAULT 'ai_suggestion'
);
"""

AI_CALLS_INDEX_DDL = """
CREATE INDEX IF NOT EXISTS idx_ai_calls_project ON ai_calls(project_id, at);
CREATE INDEX IF NOT EXISTS idx_ai_calls_status ON ai_calls(status, at);
"""

MAX_RETENTION_COUNT = 5000  # 保留最近N条
PREVIEW_CHARS = 500  # prompt/response 预览截断长度

# ai_calls列顺序（供 dict 组装）
COLUMNS = [
    "id", "at", "project_id", "entity_kind", "entity_id", "phase", "feature",
    "provider", "model", "endpoint_masked", "prompt_hash", "prompt_preview",
    "prompt_tokens", "response_hash", "response_preview", "response_tokens",
    "redaction_summary", "scope_applied", "user_confirmed", "confirmation_at",
    "latency_ms", "status", "error_code", "fallback_used", "origin_mark",
]


def init_ai_tables(conn: sqlite3.Connection):
    """初始化AI相关表（幂等）"""
    conn.executescript(AI_CALLS_DDL + AI_CALLS_INDEX_DDL)


@contextmanager
def audit_connection(path: Path):
    """短生命周期审计连接；不进入 Store 的全局事务锁。"""
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _hash(text: str | None) -> str | None:
    return hashlib.sha256(text.encode()).hexdigest()[:16] if text else None


def log_ai_call(conn: sqlite3.Connection, *,
                project_id: str | None = None,
                entity_kind: str | None = None,
                entity_id: str | None = None,
                phase: int = 1,
                feature: str,
                provider: str,
                model: str | None = None,
                endpoint_masked: str | None = None,
                prompt_text: str | None = None,
                prompt_tokens: int = 0,
                response_text: str | None = None,
                response_tokens: int = 0,
                redaction_summary: dict | None = None,
                scope_applied: list[str] | None = None,
                user_confirmed: bool = False,
                latency_ms: int = 0,
                status: str = "success",
                error_code: str | None = None,
                fallback_used: bool = False) -> int:
    """记录一次AI调用审计日志，返回记录ID"""
    now = datetime.now(timezone.utc).isoformat()

    prompt_hash = _hash(prompt_text)
    prompt_preview = prompt_text[:PREVIEW_CHARS] if prompt_text else None
    response_hash = _hash(response_text)
    response_preview = response_text[:PREVIEW_CHARS] if response_text else None

    cursor = conn.execute("""
        INSERT INTO ai_calls (at, project_id, entity_kind, entity_id, phase, feature,
            provider, model, endpoint_masked, prompt_hash, prompt_preview, prompt_tokens,
            response_hash, response_preview, response_tokens, redaction_summary,
            scope_applied, user_confirmed, confirmation_at, latency_ms, status,
            error_code, fallback_used, origin_mark)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        now, project_id, entity_kind, entity_id, phase, feature,
        provider, model, endpoint_masked, prompt_hash, prompt_preview, prompt_tokens,
        response_hash, response_preview, response_tokens,
        json.dumps(redaction_summary, ensure_ascii=False) if redaction_summary else None,
        json.dumps(scope_applied, ensure_ascii=False) if scope_applied else None,
        1 if user_confirmed else 0,
        now if user_confirmed else None,
        latency_ms, status, error_code,
        1 if fallback_used else 0,
        "ai_suggestion" if status == "success" else None,
    ))

    # 保留策略：超限删除最旧记录
    conn.execute("""
        DELETE FROM ai_calls WHERE id NOT IN (
            SELECT id FROM ai_calls ORDER BY id DESC LIMIT ?
        )
    """, (MAX_RETENTION_COUNT,))

    return cursor.lastrowid


def _row_to_dict(row) -> dict:
    d = {k: row[k] for k in COLUMNS}
    for key in ("redaction_summary", "scope_applied"):
        if d.get(key):
            try:
                d[key] = json.loads(d[key])
            except (ValueError, TypeError):
                pass
    d["user_confirmed"] = bool(d.get("user_confirmed"))
    d["fallback_used"] = bool(d.get("fallback_used"))
    return d


def query_ai_calls(conn: sqlite3.Connection, *,
                   project_id: str | None = None,
                   limit: int = 50,
                   offset: int = 0) -> tuple[list[dict], int]:
    """查询审计日志（分页），返回 (记录列表, 总数)"""
    where = ""
    params: list = []
    if project_id:
        where = "WHERE project_id = ?"
        params.append(project_id)

    count_row = conn.execute(f"SELECT COUNT(*) FROM ai_calls {where}", params).fetchone()
    total = count_row[0] if count_row else 0

    rows = conn.execute(
        f"SELECT * FROM ai_calls {where} ORDER BY id DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()

    return [_row_to_dict(r) for r in rows], total


def get_ai_call(conn: sqlite3.Connection, call_id: int) -> dict | None:
    """按ID取单条审计详情"""
    row = conn.execute("SELECT * FROM ai_calls WHERE id=?", (call_id,)).fetchone()
    return _row_to_dict(row) if row else None


def daily_token_usage(conn: sqlite3.Connection) -> int:
    """统计今日（UTC）已消耗的prompt+completion token总量，用于每日预算闸门。"""
    prefix = datetime.now(timezone.utc).date().isoformat()
    row = conn.execute(
        "SELECT COALESCE(SUM(prompt_tokens + response_tokens), 0) FROM ai_calls WHERE at LIKE ?",
        (prefix + "%",),
    ).fetchone()
    return int(row[0]) if row else 0
