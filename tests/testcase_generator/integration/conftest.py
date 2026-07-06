"""pytest 配置 — 解决 asyncpg event loop 绑定问题

集成测试分两类：
- 需真实 DB：test_callbacks_persist / test_celery_tasks（标 requires_db）
- 纯 mock：test_real_graph / test_full_pipeline（mock LLM+KB，不需 DB）
"""

import os
import socket

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5434/qa_platforms")


def _db_reachable() -> bool:
    try:
        with socket.create_connection(("localhost", 5434), timeout=0.2):
            return True
    except (OSError, ConnectionRefusedError, TimeoutError):
        return False


requires_db = pytest.mark.skipif(
    not _db_reachable(),
    reason="需 PostgreSQL (localhost:5434)，当前环境不可达",
)


@pytest.fixture(autouse=True)
def reset_db_engine_per_test():
    """每个测试前重置全局 engine，确保新 loop 创建新连接"""
    from src.platform_api.core.database import reset_engine

    reset_engine()


@pytest.fixture(autouse=True)
def isolate_settings():
    """每个集成测试结束后还原 settings 三开关 + 清 LLM 单例，防跨测试状态泄漏。"""
    from src.platform_api.core.settings import settings
    import src.testcase_generator.services.llm_client as llm_mod

    original_image = settings.image_caption_enabled
    original_entity = settings.entity_graph_enabled
    original_retrieval = settings.entity_retrieval_enabled
    original_guard = settings.test_points_completeness_guard

    yield

    settings.image_caption_enabled = original_image
    settings.entity_graph_enabled = original_entity
    settings.entity_retrieval_enabled = original_retrieval
    settings.test_points_completeness_guard = original_guard
    llm_mod._llm_client = None
