"""双重授权校验 - 配置级（enabled）+ 调用级（一次性预览令牌）。

流程：POST /api/ai/preview 通过第一道闸后生成 preview_id（内存存储，进程重启即失效）；
POST /api/ai/invoke 必须携带 preview_id 且 user_confirmed=true，令牌一次性消费防重放。
"""
from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass

PREVIEW_TTL_SECONDS = 300  # 5分钟过期


@dataclass
class PreviewToken:
    preview_id: str
    feature: str
    project_id: str
    project_version: int
    redacted_payload: dict
    redaction_summary: dict
    estimated_tokens: int
    scope_applied: list[str]
    created_at: float
    used: bool = False

    @property
    def expired(self) -> bool:
        return time.time() - self.created_at > PREVIEW_TTL_SECONDS


class GuardError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422):
        self.code = code
        self.message = message
        self.status_code = status_code


# 预览令牌存储（内存，进程重启即失效）；加锁保证线程池/事件循环并发安全。
_preview_store: dict[str, PreviewToken] = {}
_preview_lock = threading.Lock()


def create_preview_token(feature: str, project_id: str, project_version: int,
                         redacted_payload: dict, redaction_summary: dict,
                         estimated_tokens: int, scope_applied: list[str]) -> PreviewToken:
    """创建一次性预览令牌"""
    with _preview_lock:
        # 清理过期令牌
        _cleanup_expired()
        preview_id = secrets.token_urlsafe(16)
        token = PreviewToken(
            preview_id=preview_id,
            feature=feature,
            project_id=project_id,
            project_version=project_version,
            redacted_payload=redacted_payload,
            redaction_summary=redaction_summary,
            estimated_tokens=estimated_tokens,
            scope_applied=scope_applied,
            created_at=time.time(),
        )
        _preview_store[preview_id] = token
        return token


def consume_preview_token(preview_id: str) -> PreviewToken:
    """消费预览令牌（一次性，用后失效）"""
    with _preview_lock:
        token = _preview_store.get(preview_id)
        if token is None:
            raise GuardError("PREVIEW_NOT_FOUND", "预览令牌不存在或已过期，请重新预览")
        if token.expired:
            del _preview_store[preview_id]
            raise GuardError("PREVIEW_EXPIRED", "预览令牌已过期（5分钟有效），请重新预览")
        if token.used:
            raise GuardError("PREVIEW_REUSED", "预览令牌已使用，请重新预览（防重放）")
        token.used = True
        return token


def check_ai_enabled(ai_config: dict) -> None:
    """第一道闸：检查AI是否已在配置级启用"""
    if not ai_config.get("enabled", False) or (ai_config.get("provider") or "null") == "null":
        raise GuardError("AI_DISABLED", "外部AI未接入，请在设置中配置AI服务后重试", 403)


def _cleanup_expired():
    """清理过期令牌（调用方须持有 _preview_lock）"""
    now = time.time()
    expired = [k for k, v in _preview_store.items() if now - v.created_at > PREVIEW_TTL_SECONDS]
    for k in expired:
        del _preview_store[k]
