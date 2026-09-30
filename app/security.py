"""仅本机Host、同源状态变更、请求大小与浏览器安全头。"""
from starlette.responses import JSONResponse


class LocalSecurityMiddleware:
    def __init__(self, app, settings):
        self.app = app
        self.settings = settings
        self.hosts = {f"127.0.0.1:{settings.port}", f"localhost:{settings.port}"}
        self.headers = {
            "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'",
            "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer", "Cross-Origin-Resource-Policy": "same-origin",
            "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
            "Cache-Control": "no-store",
        }

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {}
        duplicates = False
        for key, value in scope.get("headers", []):
            key = key.decode("latin-1").lower()
            if key in headers and key in ("host", "origin", "content-length"):
                duplicates = True
            headers[key] = value.decode("latin-1")
        host = headers.get("host", "").lower()
        origin = headers.get("origin")
        expected_origin = "http://" + host
        method = scope["method"]
        error = None
        if duplicates or host not in self.hosts or scope.get("scheme") != "http":
            error = ("INVALID_HOST", "仅允许本机127.0.0.1或localhost使用配置端口访问", 403)
        elif origin is not None and origin != expected_origin:
            error = ("CROSS_ORIGIN_BLOCKED", "不允许跨来源请求", 403)
        elif headers.get("sec-fetch-site") not in (None, "same-origin", "none"):
            error = ("CROSS_SITE_BLOCKED", "不允许跨站请求", 403)
        elif method not in ("GET", "HEAD") and origin != expected_origin:
            error = ("ORIGIN_REQUIRED", "状态变更必须携带与Host一致的本机Origin", 403)
        elif method == "OPTIONS":
            error = ("CORS_DISABLED", "本应用不开放跨域访问", 403)
        limit = self.settings.max_upload + 1024 * 1024
        if "content-length" in headers:
            try:
                length = int(headers["content-length"])
                if length < 0 or length > limit:
                    error = ("REQUEST_TOO_LARGE", "请求大小超出安全限制", 413)
            except ValueError:
                error = ("INVALID_LENGTH", "请求长度格式无效", 400)
        async def secure_send(message):
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                existing = {k.lower() for k, v in response_headers}
                response_headers.extend((k.lower().encode(), v.encode()) for k, v in self.headers.items() if k.lower().encode() not in existing)
                message["headers"] = response_headers
            await send(message)
        if error:
            code, message, status = error
            response = JSONResponse({"code": code, "message": message}, status_code=status)
            return await response(scope, receive, secure_send)
        size = 0
        async def bounded_receive():
            nonlocal size
            message = await receive()
            if message["type"] == "http.request":
                size += len(message.get("body", b""))
                if size > limit:
                    from .core import DomainError
                    raise DomainError("REQUEST_TOO_LARGE", "请求大小超出安全限制", 413)
            return message
        await self.app(scope, bounded_receive, secure_send)
