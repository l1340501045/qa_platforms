"""pytest 配置 — 解决 asyncpg event loop 绑定问题"""

import os
import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5434/qa_platforms")


@pytest.fixture(autouse=True)
def reset_db_engine_per_test():
    """每个测试前重置全局 engine，确保新 loop 创建新连接"""
    from src.platform_api.core.database import reset_engine

    reset_engine()
