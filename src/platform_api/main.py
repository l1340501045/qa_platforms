"""FastAPI 应用入口 + 中间件链"""

import uuid

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from src.platform_api.api.v1 import v1_router
from src.platform_api.core.exceptions import (
    ApiError,
    api_error_handler,
    request_validation_error_handler,
    unhandled_error_handler,
)
from src.platform_api.core.settings import settings

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    docs_url="/docs" if settings.debug else None,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next) -> Response:
    """为每个请求注入唯一 request_id"""
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


# 注册统一异常处理器
app.add_exception_handler(ApiError, api_error_handler)  # type: ignore[arg-type]
app.add_exception_handler(RequestValidationError, request_validation_error_handler)  # type: ignore[arg-type]
app.add_exception_handler(Exception, unhandled_error_handler)  # type: ignore[arg-type]


# 注册 v1 路由
app.include_router(v1_router)


@app.get("/health")
async def health_check() -> dict:
    """存活探针"""
    return {"status": "ok", "version": settings.app_version}
