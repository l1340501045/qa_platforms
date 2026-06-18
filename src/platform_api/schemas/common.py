"""公共 Pydantic Schema：分页、标准响应包装"""

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageParams(BaseModel):
    """分页请求参数"""

    page: int = Field(default=1, ge=1, description="页码")
    per_page: int = Field(default=20, ge=1, le=100, description="每页数量")


class PaginatedResponse(BaseModel, Generic[T]):
    """分页响应"""

    items: list[T]
    total: int
    page: int
    per_page: int
    total_pages: int


class ApiResponse(BaseModel, Generic[T]):
    """标准 API 响应包装"""

    code: int = 0
    message: str = "success"
    data: T | None = None
