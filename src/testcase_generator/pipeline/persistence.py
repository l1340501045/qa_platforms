"""流水线持久化 checkpointer

历史背景：原先用 langgraph-checkpoint-redis 的 RedisSaver，但：
1. RedisSaver 是同步实现，配 LangGraph 的异步 `astream` 会在 aget_tuple 抛 NotImplementedError；
2. RedisSaver/AsyncRedisSaver 依赖 Redis Stack 的 RediSearch/RedisJSON 模块，
   而部署的是纯 redis:7-alpine，无这些模块，根本无法工作。

改用 AsyncPostgresSaver：复用已部署的 Postgres（无需额外模块），异步原生，
且持久化到 DB，支持 Gate NO_GO 后跨 Celery 任务的断点续跑。

注意：必须在「任务自身的事件循环」内打开 saver（每个 Celery 任务用独立
asyncio.run），故对外暴露异步上下文管理器，由调用方在任务内 `async with` 打开。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from src.platform_api.core.settings import settings

# setup() 创建 checkpoint 相关表是幂等的，但无需每个任务都跑迁移检查。
# 进程级只跑一次即可（concurrency=1 下安全）。
_setup_done = False


def _pg_conninfo() -> str:
    """把 SQLAlchemy 的 asyncpg URL 转成 psycopg 可用的 conninfo"""
    return settings.database_url.replace("+asyncpg", "")


@asynccontextmanager
async def open_async_checkpointer() -> AsyncIterator[AsyncPostgresSaver]:
    """在当前事件循环内打开异步 Postgres checkpointer

    用法：
        async with open_async_checkpointer() as checkpointer:
            app = compile_pipeline(checkpointer=checkpointer)
            async for event in app.astream(...):
                ...
    """
    global _setup_done
    async with AsyncPostgresSaver.from_conn_string(_pg_conninfo()) as checkpointer:
        if not _setup_done:
            await checkpointer.setup()
            _setup_done = True
        yield checkpointer
