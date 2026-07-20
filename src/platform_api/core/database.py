"""数据库连接与 async session 工厂 — 支持 lazy 初始化（便于测试注入独立实例）"""

import os
from collections.abc import AsyncGenerator
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.platform_api.core.settings import settings

# 延迟初始化：首次访问时创建（允许测试在 import 前覆盖 DATABASE_URL）
_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def get_engine() -> AsyncEngine:
    """获取或创建全局 engine（lazy）"""
    global _engine
    if _engine is None:
        # Celery worker 每个任务用 asyncio.run() 新建事件循环，QueuePool 会跨循环复用
        # asyncpg 连接，导致 "another operation is in progress" / event loop closed。
        # worker 模式下改用 NullPool（每次连接用完即弃），彻底规避跨循环连接复用。
        if os.environ.get("QA_WORKER_MODE") == "1":
            _engine = create_async_engine(
                settings.database_url,
                poolclass=NullPool,
                echo=settings.debug,
                hide_parameters=True,
            )
        else:
            _engine = create_async_engine(
                settings.database_url,
                pool_size=settings.db_pool_size,
                max_overflow=settings.db_max_overflow,
                echo=settings.debug,
                hide_parameters=True,
            )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """获取或创建全局 session factory（lazy）"""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


def reset_engine() -> None:
    """重置全局 engine（测试用：强制下次访问重新创建）"""
    global _engine, _session_factory
    _engine = None
    _session_factory = None


# 兼容旧代码：保持 async_session_factory 作为属性可用
class _SessionFactoryProxy:
    """代理对象，调用时返回 lazy session factory 的 session"""

    def __call__(self):
        return get_session_factory()()

    def __getattr__(self, name):
        return getattr(get_session_factory(), name)


async_session_factory = _SessionFactoryProxy()


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖注入用的 session 生成器"""
    async with get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
