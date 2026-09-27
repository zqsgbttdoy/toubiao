"""AI Provider抽象层：NullProvider默认降级，Ollama/OpenAI兼容端点走httpx。

约定：
- 全部Provider使用OpenAI兼容的 /chat/completions 协议，stream=False（Phase 1不做流式）。
- 投标场景需要稳定输出，默认低温（temperature=0.2）。
- 连接错误、超时、HTTP错误统一转换为 AIProviderError，由路由层降级并记审计。
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class AIRequest:
    feature: str  # "summarize"|"classify"|"generate_section"|...
    messages: list[dict]  # OpenAI格式 [{"role":"...","content":"..."}]
    max_tokens: int = 2048
    temperature: float = 0.2  # 投标场景需稳定，低温
    response_format: dict | None = None
    stream: bool = False


@dataclass(frozen=True)
class AIResponse:
    text: str
    model: str
    provider: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    finish_reason: str  # "stop"|"length"|"error"
    raw_id: str | None = None


class AIDisabledError(Exception):
    def __init__(self, code: str = "AI_DISABLED", message: str = "外部AI未接入，当前为本地规则模式"):
        self.code = code
        self.message = message


class AIProviderError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message


class AIProvider(ABC):
    name: str = "null"

    @abstractmethod
    async def chat(self, req: AIRequest) -> AIResponse: ...

    @abstractmethod
    async def health(self) -> dict: ...

    @abstractmethod
    async def embeddings(self, texts: list[str]) -> list[list[float]]: ...

    async def close(self):
        """释放底层HTTP客户端；NullProvider无资源，默认空实现。"""


class NullProvider(AIProvider):
    """默认：external_ai=False时使用，所有调用立即降级。"""
    name = "null"

    async def chat(self, req: AIRequest) -> AIResponse:
        raise AIDisabledError()

    async def health(self) -> dict:
        return {"status": "disabled", "external_ai": False, "provider": "null", "models": []}

    async def embeddings(self, texts: list[str]) -> list[list[float]]:
        raise AIDisabledError()


class OllamaProvider(AIProvider):
    """本地Ollama（OpenAI兼容API，base_url需含/v1）"""
    name = "ollama"

    def __init__(self, base_url: str = "http://127.0.0.1:11434/v1",
                 model: str = "qwen2.5:7b-instruct",
                 embedding_model: str = "bge-m3",
                 timeout: float = 120.0,
                 api_key: str = "ollama"):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.embedding_model = embedding_model
        self.api_key = api_key
        self._client: httpx.AsyncClient | None = None
        self._timeout = timeout

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self._timeout,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        return self._client

    async def chat(self, req: AIRequest) -> AIResponse:
        model = getattr(req, "model", None) or self.model
        payload: dict = {
            "model": model,
            "messages": req.messages,
            "max_tokens": req.max_tokens,
            "temperature": req.temperature,
            "stream": False,
        }
        if req.response_format:
            payload["response_format"] = req.response_format

        start = time.perf_counter()
        try:
            r = await self.client.post("/chat/completions", json=payload)
            r.raise_for_status()
        except httpx.TimeoutException:
            raise AIProviderError("AI_TIMEOUT", f"AI推理超时（{self._timeout:g}s）")
        except httpx.HTTPStatusError as e:
            raise AIProviderError("AI_HTTP_ERROR", f"AI服务返回错误: {e.response.status_code}")
        except httpx.ConnectError:
            raise AIProviderError("AI_UNREACHABLE", "无法连接AI服务，请确认Ollama已启动")
        except httpx.HTTPError as e:
            # 读中断/协议错误等其余传输异常也必须降级，不得逃逸成 500。
            raise AIProviderError("AI_TRANSPORT_ERROR", f"AI服务连接异常: {type(e).__name__}")

        latency_ms = int((time.perf_counter() - start) * 1000)
        try:
            data = r.json()
        except ValueError:
            raise AIProviderError("AI_BAD_RESPONSE", "AI服务响应不是合法JSON")
        try:
            choice = data["choices"][0]
            text = choice["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise AIProviderError("AI_BAD_RESPONSE", "AI服务响应结构异常，缺少choices内容")
        usage = data.get("usage") or {}

        return AIResponse(
            text=text,
            model=data.get("model") or model,
            provider=self.name,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            latency_ms=latency_ms,
            finish_reason=choice.get("finish_reason") or "stop",
            raw_id=data.get("id"),
        )

    async def health(self) -> dict:
        """探活：优先Ollama原生 /api/tags 取模型列表（/v1/models 在部分版本需鉴权），失败再走OpenAI兼容端点。"""
        try:
            native = self.base_url.removesuffix("/v1") + "/api/tags"
            r = await self.client.get(native)
            r.raise_for_status()
            models = [m.get("name") or m.get("model", "") for m in r.json().get("models", [])]
            return {"status": "ok", "external_ai": True, "provider": self.name,
                    "model": self.model, "models": [m for m in models if m], "base_url": self.base_url}
        except Exception:
            pass
        try:
            r = await self.client.get("/models")
            r.raise_for_status()
            models = [m["id"] for m in r.json().get("data", [])]
            return {"status": "ok", "external_ai": True, "provider": self.name,
                    "model": self.model, "models": models, "base_url": self.base_url}
        except Exception as e:
            return {"status": "error", "external_ai": True, "provider": self.name,
                    "error": type(e).__name__, "models": []}

    async def embeddings(self, texts: list[str]) -> list[list[float]]:
        try:
            r = await self.client.post("/embeddings", json={
                "model": self.embedding_model, "input": texts,
            })
            r.raise_for_status()
            return [d["embedding"] for d in r.json()["data"]]
        except httpx.ConnectError:
            raise AIProviderError("AI_UNREACHABLE", "无法连接AI服务")
        except AIProviderError:
            raise
        except Exception as e:
            raise AIProviderError("AI_EMBEDDING_ERROR", f"向量计算失败: {type(e).__name__}")

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()


class OpenAICompatProvider(OllamaProvider):
    """自定义OpenAI兼容端点（含云端）；协议一致，仅探活固定走 /models。"""
    name = "openai_compat"

    async def health(self) -> dict:
        try:
            r = await self.client.get("/models")
            r.raise_for_status()
            models = [m["id"] for m in r.json().get("data", [])]
            return {"status": "ok", "external_ai": True, "provider": self.name,
                    "model": self.model, "models": models, "base_url": self.base_url}
        except Exception as e:
            return {"status": "error", "external_ai": True, "provider": self.name,
                    "error": type(e).__name__, "models": []}


# feature级超时上限（秒）：摘要/分类60s，生成180s；与配置timeout取较小值。
FEATURE_TIMEOUTS = {"summarize": 60.0, "classify": 60.0, "generate_section": 180.0}


def feature_timeout(configured: float, feature: str) -> float:
    return min(configured, FEATURE_TIMEOUTS.get(feature, 60.0))


def build_provider(config: dict, api_key: str) -> AIProvider:
    """按ai_config实体实例化Provider；provider为null或未启用时返回NullProvider。

    api_key 由调用方（router）解码后传入，本模块不感知存储编码。
    """
    name = config.get("provider") or "null"
    if name == "null" or not config.get("enabled"):
        return NullProvider()
    if name == "ollama":
        return OllamaProvider(base_url=config["base_url"], model=config["model"],
                              embedding_model=config.get("embedding_model") or "bge-m3",
                              timeout=float(config.get("timeout_seconds") or 120.0),
                              api_key=api_key or "ollama")
    if name == "openai_compat":
        return OpenAICompatProvider(base_url=config["base_url"], model=config["model"],
                                    embedding_model=config.get("embedding_model") or "",
                                    timeout=float(config.get("timeout_seconds") or 120.0),
                                    api_key=api_key or "")
    raise AIProviderError("AI_CONFIG_INVALID", f"未知的AI提供方: {name}")
