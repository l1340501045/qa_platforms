"""统一异常体系 — 业务层抛异常，处理器统一渲染"""

import logging
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# 契约 §5.2 错误码集合（唯一来源）
ERROR_CODES: dict[str, tuple[int, str]] = {
    "E4001": (400, "请求参数无效"),
    "E4002": (400, "搜索参数无效"),
    "E4031": (403, "禁止跨站访问"),
    "E4041": (404, "资源不存在"),
    "E4042": (404, "通知不存在"),
    "E4043": (404, "逻辑用例不存在"),
    "E4091": (409, "资源状态冲突"),
    "E4092": (409, "状态不允许操作"),
    "E4093": (409, "版本不存在"),
    "E4131": (413, "文件过大"),
    "E4221": (422, "数据验证失败"),
    "E4291": (429, "请求频率超限"),
    "E5001": (500, "服务内部错误"),
    "E5031": (503, "服务暂不可用"),
}


class ApiError(Exception):
    """业务异常基类 — 抛出时指定 error_code"""

    def __init__(self, error_code: str, message: str | None = None, details: Any = None):
        self.error_code = error_code
        status, default_msg = ERROR_CODES.get(error_code, (500, "未知错误"))
        self.status_code = status
        self.message = message or default_msg
        self.details = details


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    """统一异常处理器 — 渲染为契约格式"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error_code": exc.error_code,
            "message": exc.message,
            "request_id": getattr(request.state, "request_id", None),
        },
    )


async def request_validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """统一返回不含原始输入的校验错误，避免 Key 被 FastAPI 默认详情回显。"""

    logger.warning(
        "Request validation failed: path=%s error_types=%s",
        request.url.path,
        [error.get("type", "unknown") for error in exc.errors()],
    )
    return JSONResponse(
        status_code=422,
        content={
            "error_code": "E4221",
            "message": "请求格式错误，请检查填写内容",
            "request_id": getattr(request.state, "request_id", None),
        },
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """未捕获异常处理器"""
    logger.error(
        "Unhandled exception: path=%s request_id=%s error_type=%s",
        request.url.path,
        getattr(request.state, "request_id", None),
        type(exc).__name__,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error_code": "E5001",
            "message": "服务内部错误",
            "request_id": getattr(request.state, "request_id", None),
        },
    )
