"""metrics 纯函数断言测试。用法：uv run python eval/retrieval/test_metrics.py"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from metrics import mrr, ndcg_at_k, recall_at_k


def test_recall():
    assert recall_at_k(["a", "b", "c"], {"a", "x"}, 3) == 0.5   # 命中 a；relevant 2 个
    assert recall_at_k(["a", "b", "c"], {"a"}, 1) == 1.0
    assert recall_at_k(["b", "a"], {"a"}, 1) == 0.0             # a 不在前 1
    assert recall_at_k(["a"], set(), 3) is None                # 负样本：无相关项 → None


def test_ndcg():
    assert ndcg_at_k(["a", "b"], {"a"}, 10) == 1.0             # 命中首位 = 理想
    v = ndcg_at_k(["b", "a"], {"a"}, 10)                        # 命中第 2 位
    assert abs(v - (1.0 / math.log2(3))) < 1e-9
    assert ndcg_at_k(["x"], set(), 10) is None


def test_mrr():
    assert mrr(["a", "b"], {"b"}) == 0.5
    assert mrr(["a"], {"a"}) == 1.0
    assert mrr(["x", "y"], {"a"}) == 0.0
    assert mrr(["x"], set()) is None


if __name__ == "__main__":
    test_recall()
    test_ndcg()
    test_mrr()
    print("metrics: all passed")
