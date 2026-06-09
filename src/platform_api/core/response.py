"""统一响应格式 — 集中实现，所有端点自动生效"""

from math import ceil
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """统一成功信封"""

    code: int = 0
    message: str = "success"
    data: T


class PaginatedData(BaseModel, Generic[T]):
    """分页数据结构"""

    items: list[T]
    total: int
    page: int
    per_page: int
    total_pages: int


class PaginationParams(BaseModel):
    """分页查询参数"""

    page: int = 1
    per_page: int = 20

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.per_page

    @property
    def limit(self) -> int:
        return min(self.per_page, 100)


def paginated_response(items: list, total: int, params: PaginationParams) -> dict:
    """构造分页响应"""
    return {
        "items": items,
        "total": total,
        "page": params.page,
        "per_page": params.per_page,
        "total_pages": ceil(total / params.per_page) if params.per_page > 0 else 0,
    }


def success(data: Any = None) -> dict:
    """快捷构造成功响应"""
    return {"code": 0, "message": "success", "data": data}
