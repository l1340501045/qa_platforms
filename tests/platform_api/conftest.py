"""platform_api 测试 conftest — 不需要 DB，只需 reset engine 避免干扰"""

import os
import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5434/qa_platforms")


@pytest.fixture(autouse=True)
def reset_db_engine_per_test():
    from src.platform_api.core.database import reset_engine

    reset_engine()
