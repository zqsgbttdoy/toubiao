"""AI辅助模块 - Phase 1只读辅助（默认禁用，NullProvider降级到本地规则）。

纪律：
- AI调用绝不在 Store.transaction() 内发起（推理秒级耗时会阻塞全局写锁）。
- Phase 1 结果只返回前端展示并记审计日志，不写任何业务实体。
- 默认 external_ai=False；前端受 CSP connect-src 'self' 限制，全部AI请求由后端代理。
"""
from .router import ai_router

__all__ = ["ai_router"]
