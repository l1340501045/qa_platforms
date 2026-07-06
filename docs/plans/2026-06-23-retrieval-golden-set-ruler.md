# 检索 Golden Set 尺子 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建一把可复用、便宜、可复现的检索质量尺子——用标注好「应召回哪些章节」的 ~60 条 query，离线对比「关键词 vs hybrid」的 Recall@3/@10、NDCG@10、MRR 与负样本噪声率，据此决定 hybrid 是否放量。

**Architecture:** 一次性冻结真实大批次 PRD 的候选集到 `candidates.json`（复跑 `parse_node`，只读 DB + 便宜分类，不碰生成）。评估器读「冻结候选 + golden_set.yaml」，对每条 query 跑 `CrossFeatureIndex.query` 开/关两档（生产口径：排除自身+全局），算指标出报告。纯指标逻辑抽成可单测的 `metrics.py`。全程只额外烧 embedding。

**Tech Stack:** Python 3.12, asyncio, `CrossFeatureIndex`（已实现 hybrid）, `EmbeddingClient`, PyYAML, 纯 Python 指标。

> 设计依据：`docs/spec/2026-06-23-retrieval-golden-set-design.md`（已评审）。

---

## 现状速查（实现前必读）

- **复用取数路径**：`.qa_probe/retrieval_diff.py` 已验证「复跑 `parse_node` 拿 `parsed_context` + 按生产口径排除自身/全局」可行，本计划沿用同款逻辑。
- **CrossFeatureIndex**（`src/testcase_generator/stages/context_utils.py`）：`async build(parsed_context)`；`async query(query_text, exclude_keys, *, top_k=3, min_score=6)` 返回 `list[GlobalSection]`（有 `.source_ref/.heading`）；读 `settings.hybrid_cross_retrieval_enabled`；`_candidates`、`_cand_vectors` 可访问。`collect_global_sections(parsed)` 返回全局章节。
- **真实大批次**：`BATCH_ID=8c1b326b-fe7b-4ba8-8350-b92adcee23dd`，`DOC_ID=f91a9bef-bc79-429c-b6fa-63b97fd892fc`，`SYS_ID=26ffd7ba-c7ee-40e2-a1ca-b9fd413d5012`；解析后 **28 候选章节 / 22 功能点**。
- **候选 source_ref 形如** `"prd:漫剧批创初版功能PRD §7.2 提交时的绑定规则"`（`expected_refs` 必须逐字一致）。
- **parse_node**：`(await parse_node({"document_id":..,"system_id":..,"generation_config":{}}))["parsed_context"]`。跑前置 `settings.entity_retrieval_enabled=False` 省一次图遍历。
- **路径引导**：`eval/retrieval/*.py` 顶部插 sys.path（仓库根 → `import src`；本目录 → `import metrics`）。**不要**做 `import eval.retrieval`（`eval` 与内建冲突）。
- **DB 已 Up**（容器 `qa-platforms-pg`，端口 5434）；embedding 走 `LLM_BASE_URL` 网关（`text-embedding-v4`）。

## File Structure

```
eval/retrieval/
  snapshot_candidates.py   # 一次性：冻结候选集 → candidates.json
  candidates.json          # 候选集快照（生成物，标注与评估的共同基准）
  metrics.py               # 纯函数：recall_at_k / ndcg_at_k / mrr（可单测）
  test_metrics.py          # metrics 断言测试（直接 uv run python 跑）
  golden_set.yaml          # ~60 条金标准（AI 起草 + 用户审）
  evaluate.py              # 评估器：读快照+金标准 → 开/关两档 → 指标 + report.md
  report.md                # 评估产出
```

---

## Chunk 1: 候选集快照

### Task 1: 冻结候选集到 candidates.json

**Files:**
- Create: `eval/retrieval/snapshot_candidates.py`
- Generates: `eval/retrieval/candidates.json`

- [ ] **Step 1: 写快照脚本**

```python
"""一次性冻结候选集快照 → eval/retrieval/candidates.json（标注与评估的共同基准）。
只读 DB + 复跑 parse_node（便宜分类，不碰生成/视觉）。用法：uv run python eval/retrieval/snapshot_candidates.py
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # 仓库根 → import src

from src.platform_api.core.settings import settings
from src.testcase_generator.stages.context_utils import (
    CrossFeatureIndex,
    collect_global_sections,
)
from src.testcase_generator.stages.parse.node import parse_node

DOC_ID = "f91a9bef-bc79-429c-b6fa-63b97fd892fc"
SYS_ID = "26ffd7ba-c7ee-40e2-a1ca-b9fd413d5012"
BATCH_ID = "8c1b326b-fe7b-4ba8-8350-b92adcee23dd"
OUT = Path(__file__).parent / "candidates.json"


async def main() -> None:
    settings.entity_retrieval_enabled = False
    settings.hybrid_cross_retrieval_enabled = False
    parsed = (await parse_node({"document_id": DOC_ID, "system_id": SYS_ID, "generation_config": {}}))["parsed_context"]
    idx = await CrossFeatureIndex.build(parsed)

    candidates = [
        {
            "source_ref": c.source_ref,
            "heading": c.heading,
            "content": c.content,
            "section_kind": c.section_kind,
            "trust_level": c.trust_level,
            "source_title": c.source_title,
        }
        for c in idx._candidates
    ]
    global_keys = [[g.source_ref or "", g.heading or ""] for g in collect_global_sections(parsed)]
    features = {f.id: {"name": f.name, "source_refs": list(f.source_refs)} for f in parsed.features}

    OUT.write_text(
        json.dumps(
            {"batch_id": BATCH_ID, "candidates": candidates, "global_keys": global_keys, "features": features},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    print(f"snapshot: {len(candidates)} candidates, {len(global_keys)} global keys, {len(features)} features → {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: 跑快照并核对**

Run: `uv run python eval/retrieval/snapshot_candidates.py`
Expected: `snapshot: 28 candidates, 8 global keys, 22 features → .../candidates.json`；`candidates.json` 存在且含 `candidates/global_keys/features` 三键。

- [ ] **Step 3: Commit**

```bash
git add eval/retrieval/snapshot_candidates.py eval/retrieval/candidates.json
git commit -m "feat(eval): 冻结检索候选集快照 candidates.json（落点③尺子）"
```

---

## Chunk 2: 指标 + 评估器

### Task 2: 指标纯函数（TDD）

**Files:**
- Create: `eval/retrieval/metrics.py`
- Test: `eval/retrieval/test_metrics.py`

- [ ] **Step 1: 写失败测试**

```python
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
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `uv run python eval/retrieval/test_metrics.py`
Expected: FAIL —— `ModuleNotFoundError: No module named 'metrics'`（尚未实现）。

- [ ] **Step 3: 实现 metrics.py**

```python
"""检索指标纯函数：recall@k / ndcg@k / mrr。relevant 为空时返回 None（负样本不计入这些均值）。"""
from __future__ import annotations

import math


def recall_at_k(ranked_keys: list[str], relevant: set[str], k: int) -> float | None:
    if not relevant:
        return None
    hit = sum(1 for key in ranked_keys[:k] if key in relevant)
    return hit / len(relevant)


def ndcg_at_k(ranked_keys: list[str], relevant: set[str], k: int) -> float | None:
    if not relevant:
        return None
    dcg = sum(1.0 / math.log2(i + 2) for i, key in enumerate(ranked_keys[:k]) if key in relevant)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(min(len(relevant), k)))
    return dcg / idcg if idcg else 0.0


def mrr(ranked_keys: list[str], relevant: set[str]) -> float | None:
    if not relevant:
        return None
    for i, key in enumerate(ranked_keys):
        if key in relevant:
            return 1.0 / (i + 1)
    return 0.0
```

- [ ] **Step 4: 跑测试，确认通过**

Run: `uv run python eval/retrieval/test_metrics.py`
Expected: `metrics: all passed`

- [ ] **Step 5: Commit**

```bash
git add eval/retrieval/metrics.py eval/retrieval/test_metrics.py
git commit -m "feat(eval): 检索指标纯函数 recall/ndcg/mrr + 单测"
```

---

### Task 3: 评估器 evaluate.py

**Files:**
- Create: `eval/retrieval/evaluate.py`
- Uses: `candidates.json`（Task 1）、`metrics.py`（Task 2）、`golden_set.yaml`（Task 4，本 Task 先用小样例验证）

- [ ] **Step 1: 写评估器**

```python
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
```

- [ ] **Step 2: 用小样例验证评估器能跑（金标准未就绪前）**

临时建 `eval/retrieval/golden_set.yaml`（2 条，验证流程；Task 4 会覆盖）：
```yaml
- id: GS-smoke-1
  feature_id: F-013
  query: "付费直投/付费ROI 的链接类型是 IAP，提交时自动绑定 IAP 监测链接"
  expected_refs:
    - "prd:漫剧批创初版功能PRD §7.2 提交时的绑定规则"
  polarity: positive
- id: GS-smoke-2
  feature_id: F-006
  query: "商品库列表每行展示商品/商品库/更新时间三列"
  expected_refs: []
  polarity: negative
```
Run: `uv run python eval/retrieval/evaluate.py`
Expected: 打印指标表（含 `向量就绪=True`），`report.md` 生成；`expected_refs` 校验通过（GS-smoke-1 的 §7.2 在候选集内）。若报 `❌ expected_refs 不在候选集`，照提示对照 `candidates.json` 修 source_ref 逐字。

- [ ] **Step 3: Commit（先不提交临时 golden_set，留待 Task 4 定稿）**

```bash
git add eval/retrieval/evaluate.py
git commit -m "feat(eval): 检索 Golden Set 评估器（关键词 vs hybrid，含 expected_refs 校验）"
```

---

## Chunk 3: 金标准数据集 + 出数决策

### Task 4: 起草并审核 golden_set.yaml（~60 条）

**Files:**
- Create/Overwrite: `eval/retrieval/golden_set.yaml`

- [ ] **Step 1: AI 按依赖簇起草 ~60 条**

读 `candidates.json`（28 候选）+ `.qa_probe/retrieval_diff_report.md` + DB `testcase.test_points`（按 `feature_id`/`dimension` 采样），按簇起草。配比：per-feature 忠实组 ~22 + 维度采样组 ~28 + 负样本 ~8 + 痛点探针 ~5。`expected_refs` **排除功能点自身章节 + 全局章节**，逐字用 `candidates.json` 里的 `source_ref`。簇与边界依据设计文档 §3.4。

- [ ] **Step 2: 用户审核簇逻辑（人在环）**

向用户呈现「按簇分组」的草稿（不是 60 条单标），确认两处边界：①权限簇铺多广（仅 F-008/09/11/28/29，还是所有含 `access_control` 的功能点）；②hub 功能 F-010 列几个联动章节。按反馈调整定稿。

- [ ] **Step 3: 校验 expected_refs 全部命中候选集**

Run: `uv run python eval/retrieval/evaluate.py`
Expected: 无 `❌ expected_refs 不在候选集` 报错（有则照提示逐字修正）。

- [ ] **Step 4: Commit**

```bash
git add eval/retrieval/golden_set.yaml
git commit -m "feat(eval): 检索 Golden Set 金标准 ~60 条（AI 起草+人工审核）"
```

---

### Task 5: 跑评估 + 解读 + 放量决策

**Files:**
- Generates: `eval/retrieval/report.md`
- Modify（记录）: `findings.md` 或 roadmap 进度日志

- [ ] **Step 1: 跑全量评估**

Run: `uv run python eval/retrieval/evaluate.py`
Expected: 指标对照表（关键词 vs hybrid 的 Recall@3/@10、NDCG@10、MRR、负样本噪声率）+ `report.md` 逐条明细；`向量就绪=True`。

- [ ] **Step 2: 解读并给决策建议**

按设计文档 §5 口径判读：
- hybrid 正样本 Recall@10/NDCG@10 净增明显且负样本噪声率不升 → **建议放量**；
- 正样本有增但噪声率上升 → **先调参**（cosine 下限 / `rrf_k` / `pool`）复测；
- 正样本无净增 → **维持关**，重审 query 构造或转落点②。
- 铁律：aggregate（n≈60）只看方向，结合逐条漏召回明细人工判断。

- [ ] **Step 3: 记录结论**

把指标对照 + 决策建议追加到 `findings.md`，并更新 `docs/plans/testcase-generation-best-practice-roadmap.md` 落点③状态（⬜→🟡/✅）与进度日志。

```bash
git add findings.md docs/plans/testcase-generation-best-practice-roadmap.md eval/retrieval/report.md
git commit -m "docs(eval): 检索尺子首轮结论 + 落点③进度更新"
```

---

## 总验收标准

- [ ] `eval/retrieval/candidates.json` 已冻结（28 候选 / 22 功能点 / 8 全局键）。
- [ ] `uv run python eval/retrieval/test_metrics.py` 通过。
- [ ] `eval/retrieval/golden_set.yaml` ~60 条，`expected_refs` 全部校验通过，经用户审核。
- [ ] `uv run python eval/retrieval/evaluate.py` 一条命令出指标对照 + `report.md`，区分正/负样本。
- [ ] 产出「放量 / 调参 / 不放量」的明确建议并记录。

## 风险与回退

- **向量未就绪**：若报告 `向量就绪=False`，说明 embedding 网关异常（hybrid 实际未生效，ON==OFF）→ 排查网关/批大小后重跑，勿据此下结论。
- **候选漂移**：`section_kind` 走 LLM、偶有波动 → 已用 `candidates.json` 冻结；PRD 变更才显式重跑 Task 1 重生成快照（并复核 golden_set 的 expected_refs）。
- **小样本**：n≈60，aggregate 仅看方向，以逐条明细兜底，不宣称统计显著。
- **零代码影响生产**：本计划仅新增 `eval/retrieval/` 离线工具，不改任何生产代码、不改 hybrid 开关默认值。
