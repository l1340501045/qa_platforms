"""检索 Golden Set 评估器：关键词 vs hybrid，正样本 Recall@3/@10 + NDCG@10 + MRR，负样本噪声率。
读 candidates.json（冻结候选）+ golden_set.yaml；只跑 embedding，不碰生成。
用法：uv run python eval/retrieval/evaluate.py
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))                 # 本目录 → import metrics
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # 仓库根 → import src

import yaml

from metrics import mrr, ndcg_at_k, recall_at_k
from src.platform_api.core.settings import settings
from src.testcase_generator.stages.context_utils import CrossFeatureIndex

HERE = Path(__file__).parent
CAND = HERE / "candidates.json"
GOLDEN = HERE / "golden_set.yaml"
REPORT = HERE / "report.md"
TOP_K = 10


class _Sec:
    def __init__(self, d: dict) -> None:
        self.heading = d["heading"]
        self.content = d["content"]
        self.source_ref = d["source_ref"]
        self.section_kind = d["section_kind"]


class _Src:
    def __init__(self, title: str, trust: int, sections: list) -> None:
        self.title = title
        self.trust_level = trust
        self.sections = sections


class _Ctx:
    def __init__(self, sources: list) -> None:
        self.sources = sources


def _load_ctx(data: dict) -> _Ctx:
    # 候选已全部 trust<=2 且 spec/summary，归到一个 duck source（trust=1）即可重建 _candidates
    secs = [_Sec(c) for c in data["candidates"]]
    title = data["candidates"][0]["source_title"] if data["candidates"] else "PRD"
    return _Ctx([_Src(title, 1, secs)])


async def _run(ctx: _Ctx, golden: list, exclude_for, enabled: bool):
    settings.hybrid_cross_retrieval_enabled = enabled
    idx = await CrossFeatureIndex.build(ctx)
    hits = {}
    for e in golden:
        res = await idx.query(e["query"], exclude_for(e.get("feature_id", "")), top_k=TOP_K, min_score=6)
        hits[e["id"]] = [r.source_ref for r in res]
    return idx, hits


def _agg(golden: list, hits: dict) -> tuple:
    pos = [e for e in golden if e.get("polarity", "positive") == "positive" and e.get("expected_refs")]
    neg = [e for e in golden if e.get("polarity") == "negative"]

    def mean(vals: list) -> float:
        vals = [v for v in vals if v is not None]
        return sum(vals) / len(vals) if vals else 0.0

    r3 = mean([recall_at_k(hits[e["id"]], set(e["expected_refs"]), 3) for e in pos])
    r10 = mean([recall_at_k(hits[e["id"]], set(e["expected_refs"]), 10) for e in pos])
    nd = mean([ndcg_at_k(hits[e["id"]], set(e["expected_refs"]), 10) for e in pos])
    mr = mean([mrr(hits[e["id"]], set(e["expected_refs"])) for e in pos])
    noise = (sum(1 for e in neg if hits[e["id"]]) / len(neg)) if neg else 0.0
    return r3, r10, nd, mr, noise, len(pos), len(neg)


async def main() -> None:
    settings.entity_retrieval_enabled = False
    data = json.loads(CAND.read_text(encoding="utf-8"))
    ctx = _load_ctx(data)
    global_keys = {tuple(k) for k in data["global_keys"]}
    feat_refs = {fid: set(v["source_refs"]) for fid, v in data["features"].items()}
    cand_keys = {(c["source_ref"], c["heading"]) for c in data["candidates"]}
    cand_refs = {c["source_ref"] for c in data["candidates"]}

    golden = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))

    # 校验 expected_refs 都在候选集（防笔误/章节漂移被静默算漏召回）
    bad = [(e["id"], ref) for e in golden for ref in e.get("expected_refs", []) if ref not in cand_refs]
    if bad:
        print("❌ expected_refs 不在候选集，请修正 golden_set.yaml：")
        for gid, ref in bad:
            print(f"   {gid}: {ref}")
        sys.exit(1)

    def exclude_for(fid: str) -> set:
        return set(global_keys) | {k for k in cand_keys if k[0] in feat_refs.get(fid, set())}

    _, kw = await _run(ctx, golden, exclude_for, enabled=False)
    idx_on, hy = await _run(ctx, golden, exclude_for, enabled=True)
    vec_ready = idx_on._cand_vectors is not None

    k, h = _agg(golden, kw), _agg(golden, hy)
    head = [
        "# 检索 Golden Set 评估报告\n",
        f"- 候选={len(data['candidates'])}　golden={len(golden)}　正样本={k[5]}　负样本={k[6]}　向量就绪={vec_ready}\n",
        "| 指标 | 关键词 | hybrid |",
        "|---|---|---|",
        f"| Recall@3 | {k[0]:.3f} | {h[0]:.3f} |",
        f"| Recall@10 | {k[1]:.3f} | {h[1]:.3f} |",
        f"| NDCG@10 | {k[2]:.3f} | {h[2]:.3f} |",
        f"| MRR | {k[3]:.3f} | {h[3]:.3f} |",
        f"| 负样本噪声率 | {k[4]:.3f} | {h[4]:.3f} |",
        "",
    ]
    detail = ["## 逐条明细\n"]
    for e in golden:
        detail.append(f"### {e['id']} {e.get('feature_id','')} ({e.get('polarity','positive')})")
        detail.append(f"- query: {e['query'][:120]}")
        detail.append(f"- expected: {sorted(set(e.get('expected_refs', []))) or '（负样本）'}")
        detail.append(f"- 关键词: {kw[e['id']][:5]}")
        detail.append(f"- hybrid : {hy[e['id']][:5]}\n")
    REPORT.write_text("\n".join(head + detail), encoding="utf-8")
    print("\n".join(head))
    print(f"明细 → {REPORT}")


if __name__ == "__main__":
    asyncio.run(main())
