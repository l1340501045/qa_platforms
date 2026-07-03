"""离线评估：语义去重（hybrid）vs 纯词面 压缩率对照。

读 .audit/<batch>/modules/<模块>/branches/**/cases.jsonl（兼容旧版 modules/*.cases.jsonl）
→ 构造 DedupCase → 算 embedding →
跑 find_duplicates（语义开/关各一次）→ 打印 duplicate 数、唯一数、压缩率，
并随机抽 10 个"仅语义折叠"的对供人工判真伪。

成本仅 embedding（分钱级）。向量外部算好传入，find_duplicates 仍纯同步。

用法：
    uv run python scripts/dedup_offline_eval.py <batch_id>
    uv run python scripts/dedup_offline_eval.py 278c211f-6f25-4970-a425-9db94cbc8ff7
"""

from __future__ import annotations

import asyncio
import random
import sys
from pathlib import Path

# 让脚本可从仓库根直接跑（uv run python scripts/...）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.audit_case_reader import iter_case_records, resolve_batch_path  # noqa: E402
from src.knowledge_base.services.embedding.embedding_client import EmbeddingClient  # noqa: E402
from src.testcase_generator.stages.dedup.clustering import DedupCase, find_duplicates  # noqa: E402

_SAMPLE_PAIRS = 10


def load_cases(batch_id: str) -> list[DedupCase]:
    batch_path = resolve_batch_path(batch_id)
    if not batch_path.exists():
        raise SystemExit(f"batch 不存在：{batch_path}")

    cases: list[DedupCase] = []
    for _, _, record in iter_case_records(batch_path):
        cases.append(
            DedupCase(
                case_id=record["id"],
                feature_id=record.get("test_point_id") or "",
                title=record.get("title") or "",
                text=" ".join(record.get("expected_results") or []),
                dimension=" ".join(record.get("dimensions") or []),
                # 离线导出 JSON 无 rule_id → rule_codes 缺失，safe_dedup 护栏退化；
                # 护栏真实性以 tests/testcase_generator/test_semantic_dedup.py 单测为准。
            )
        )
    if not cases:
        raise SystemExit(f"找不到 cases.jsonl：{batch_path / 'modules'}")
    return cases


async def compute_embeddings(cases: list[DedupCase]) -> dict[str, list[float]]:
    texts = [(c.title or "") + " " + (c.text or "") for c in cases]
    client = EmbeddingClient()
    vectors = await client.embed_batch(texts)
    if len(vectors) != len(cases):
        raise SystemExit(f"embedding 数量不匹配：{len(vectors)} != {len(cases)}")
    return {c.case_id: v for c, v in zip(cases, vectors, strict=True) if v}


def _summary(total: int, dup_map: dict[str, str]) -> dict:
    return {
        "total": total,
        "duplicate_count": len(dup_map),
        "unique_after_dedup": total - len(dup_map),
        "compression": f"{(len(dup_map) / total * 100):.1f}%" if total else "0%",
    }


def _semantic_only_pairs(
    cases: list[DedupCase], lex_dup: dict[str, str], sem_dup: dict[str, str]
) -> list[tuple[DedupCase, DedupCase]]:
    """仅被语义 pass 折叠、词面 pass 抓不到的对（dup_map 多出来的部分）。"""
    by_id = {c.case_id: c for c in cases}
    pairs = []
    seen: set[frozenset[str]] = set()
    for dup_id, canon_id in sem_dup.items():
        # 词面已折叠的跳过（dup_id 或 canon_id 已在 lex_dup 中）
        if dup_id in lex_dup:
            continue
        key = frozenset((dup_id, canon_id))
        if key in seen:
            continue
        seen.add(key)
        pairs.append((by_id[dup_id], by_id[canon_id]))
    return pairs


async def main(batch_id: str) -> None:
    cases = load_cases(batch_id)
    print(f"载入 {len(cases)} 条用例（batch {batch_id}）")

    print("计算 embedding …")
    embeddings = await compute_embeddings(cases)
    print(f"  得到 {len(embeddings)} 条向量")

    lex_dup = find_duplicates(cases, safe_dedup_enabled=False)
    sem_dup = find_duplicates(
        cases,
        safe_dedup_enabled=False,
        embeddings=embeddings,
        semantic_threshold=0.86,
        semantic_cross_tp_threshold=0.90,
    )

    print("\n=== 压缩率对照 ===")
    print(f"纯词面：  {_summary(len(cases), lex_dup)}")
    print(f"hybrid：  {_summary(len(cases), sem_dup)}")

    pairs = _semantic_only_pairs(cases, lex_dup, sem_dup)
    print(f"\n=== 仅语义折叠对（共 {len(pairs)} 对），抽 {_SAMPLE_PAIRS} 个供人工判真伪 ===")
    if pairs:
        sample = random.sample(pairs, min(_SAMPLE_PAIRS, len(pairs)))
        for i, (a, b) in enumerate(sample, 1):
            print(f"\n[{i}] TP={a.feature_id[:8]}… / {b.feature_id[:8]}…")
            print(f"  A: {a.title}")
            print(f"  B: {b.title}")
            if a.text or b.text:
                print(f"  A.exp: {a.text[:80]}")
                print(f"  B.exp: {b.text[:80]}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("用法：uv run python scripts/dedup_offline_eval.py <batch_id>")
    asyncio.run(main(sys.argv[1]))
