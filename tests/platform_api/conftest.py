"""platform_api 测试 conftest

集成测试（test_*_integration.py）需真实 PostgreSQL；
单元测试（test_contract_conformance 等）不需 DB。
DB 不可达时集成测试自动 skip。
"""

import os
import socket
from urllib.parse import urlsplit

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_database_url = os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5434/qa_platforms_taxonomy_test",
)
_database_name = urlsplit(_database_url).path.rsplit("/", 1)[-1]
if "test" not in _database_name.lower() and os.environ.get("PLATFORM_API_TEST_ALLOW_NON_TEST_DATABASE") != "1":
    raise RuntimeError(
        "platform_api_tests_require_isolated_database:"
        "数据库名必须包含 test；确需覆盖时显式设置 PLATFORM_API_TEST_ALLOW_NON_TEST_DATABASE=1"
    )


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


_TAXONOMY_IMMUTABILITY_TRIGGERS = (
    ("taxonomy_backfill_runs", "trg_guard_taxonomy_backfill_run_mutation"),
    (
        "requirement_taxonomy_mapping_related_concepts",
        "trg_guard_reviewed_mapping_related_mutation",
    ),
    ("requirement_taxonomy_mappings", "trg_guard_reviewed_mapping_mutation"),
    ("taxonomy_nodes", "trg_guard_taxonomy_node_mutation"),
    ("taxonomy_versions", "trg_guard_taxonomy_version_mutation"),
)


async def set_taxonomy_immutability_triggers(session: AsyncSession, *, enabled: bool) -> None:
    """仅供测试夹具精确清理随机数据；业务 DELETE 仍必须经过触发器。"""
    action = "ENABLE" if enabled else "DISABLE"
    for table_name, trigger_name in _TAXONOMY_IMMUTABILITY_TRIGGERS:
        await session.execute(text(f"ALTER TABLE testcase.{table_name} {action} TRIGGER {trigger_name}"))


@pytest.fixture(autouse=True)
def reset_db_engine_per_test():
    from src.platform_api.core.database import reset_engine

    reset_engine()
