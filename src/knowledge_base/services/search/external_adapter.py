"""跨系统检索适配器接口 — 抽象外部数据源检索"""

import logging
from abc import ABC, abstractmethod
from uuid import UUID

from src.knowledge_base.schemas.common import SearchResult

logger = logging.getLogger(__name__)


class ExternalSearchAdapter(ABC):
    """跨系统检索适配器基类"""

    @abstractmethod
    async def search(
        self,
        query: str,
        system_id: UUID,
        top_k: int = 5,
    ) -> list[SearchResult]:
        """执行跨系统检索"""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """检查外部系统可用性"""
        ...


class NoopExternalAdapter(ExternalSearchAdapter):
    """空实现 — 当无外部系统时使用"""

    async def search(
        self,
        query: str,
        system_id: UUID,
        top_k: int = 5,
    ) -> list[SearchResult]:
        """不执行任何检索"""
        return []

    async def health_check(self) -> bool:
        """始终健康"""
        return True
