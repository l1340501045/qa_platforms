"""线A 回归：统计指定 batch 的 priority 分布 + dimensions 标签种类，对比改造前后。

用法：uv run python scripts/metadata_regression.py <batch_id>
"""
from __future__ import annotations

import asyncio
import sys
from collections import Counter
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from src.platform_api.core.database import get_session_factory  # noqa: E402
from src.platform_api.models.testcase import TestCase  # noqa: E402


async def main() -> None:
    batch_id = UUID(sys.argv[1])
    async with get_session_factory()() as s:
        rows = (await s.execute(select(TestCase).where(TestCase.batch_id == batch_id))).scalars().all()
    n = len(rows)
    prio = Counter(c.priority for c in rows)
    dims: Counter[str] = Counter()
    for c in rows:
        for d in (c.dimensions or []):
            dims[d if isinstance(d, str) else str(d)] += 1
    p0 = prio.get("P0", 0)
    print(f"batch {batch_id} | 用例 {n}")
    print(f"priority 分布: {dict(prio)}  | P0 占比 {p0 / max(n, 1) * 100:.1f}%")
    print(f"维度标签种类数: {len(dims)}")
    print(f"非 enum/other 标签(若有): {[k for k in dims if k == 'other']}")
    print("维度 top20:", dims.most_common(20))


if __name__ == "__main__":
    asyncio.run(main())
