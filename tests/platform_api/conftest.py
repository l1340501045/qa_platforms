"""platform_api 测试 conftest

集成测试（test_*_integration.py）需真实 PostgreSQL；
单元测试（test_contract_conformance 等）不需 DB。
DB 不可达时集成测试自动 skip。
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
    from src.platform_api.core.database import reset_engine

    reset_engine()
