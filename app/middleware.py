"""Request logging and rate limiting middleware."""

import time
import logging
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger("sonic_insights")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        ms = (time.perf_counter() - start) * 1000
        logger.info("%s %s → %d (%.1fms)",
                     request.method, request.url.path,
                     response.status_code, ms)
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_requests: int = 1000, window_seconds: int = 60):
        super().__init__(app)
        self.max = max_requests
        self.window = window_seconds
        self.hits: dict[str, list[float]] = defaultdict(list)
        self.exempt_paths = {"/health", "/docs", "/redoc"}

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in self.exempt_paths or path.endswith('/openapi.json'):
            return await call_next(request)

        ip = request.client.host if request.client else "unknown"
        now = time.time()
        self.hits[ip] = [t for t in self.hits[ip] if t > now - self.window]
        if len(self.hits[ip]) >= self.max:
            return JSONResponse({"detail": "Rate limit exceeded"}, 429)
        self.hits[ip].append(now)
        return await call_next(request)
