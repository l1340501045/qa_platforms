"""回归测试：write-cases 按测试点条数切批，但绝不减少测试点/用例。

老板关切点：硬切批会不会"少设计用例"？答案是不会——切批只是把同一功能点已定的
测试点分多次调用、再聚合，切批前后测试点总数恒等。本测试用来锁死这个不变量，
防止未来改动悄悄丢用例。
"""

from src.testcase_generator.stages.write_cases.node import _split_by_count, MAX_TPS_PER_BATCH


def test_small_feature_not_split():
    tps = list(range(MAX_TPS_PER_BATCH))  # 恰好等于上限
    assert _split_by_count(tps) == [tps]


def test_empty_returns_empty():
    assert _split_by_count([]) == []


def test_large_feature_split_preserves_all():
    tps = list(range(133))  # 模拟 F-002 的 133 个测试点
    batches = _split_by_count(tps)
    # 每批不超过上限
    assert all(len(b) <= MAX_TPS_PER_BATCH for b in batches)
    # 切批前后测试点一个不少（核心不变量：用例不会被少设计）
    flattened = [tp for b in batches for tp in b]
    assert flattened == tps
    assert sum(len(b) for b in batches) == 133


def test_split_count_matches_ceil():
    import math
    for n in (1, 12, 13, 50, 100, 133):
        batches = _split_by_count(list(range(n)))
        assert len(batches) == math.ceil(n / MAX_TPS_PER_BATCH)
