# Hybrid 跨功能点规格检索 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `write_cases`/`verify` 的「跨功能点规格检索」从纯关键词词项重叠升级为 Hybrid（关键词 + 向量 + RRF 融合），减少「深层规格漏召回 → 用例被误判为『需求待确认』空壳」的质量问题。

**Architecture:** 不改候选集来源（仍是运行时 `parsed_context` 的 spec/summary sections，字段完整）。对同一候选集做两路召回——关键词路（现有词项重叠）+ 向量路（对候选 content 实时 embedding + cosine），用 RRF（按 rank 融合，k 默认 60）合并。全程灰度开关默认关闭（关闭时行为与现状逐字节一致、零额外开销）；开启时若 embedding 失败则自动降级回纯关键词，绝不阻断生成。**不动 `document_embeddings` 的用途**（那是另一套分块、缺 section_kind，本次只在内存候选集上做 hybrid）。

**Tech Stack:** Python 3.12, asyncio, `EmbeddingClient`（自建网关 `text-embedding-v4` / 1024 维 / 单批上限 10，已修复可用）, RRF, pytest。

---

## 现状速查（实现前必读，已逐行核对）

**核心类 `CrossFeatureIndex`** — `src/testcase_generator/stages/context_utils.py`
- `_CROSS_MIN_SCORE = 6`（line 66）：关键词命中下限。
- `_salient_terms(text) -> set[str]`（line 69-81）：CJK 3-gram + 长度≥3 的 ascii 词。
- `@dataclass(frozen=True) GlobalSection`（line 44-53）：字段 `source_title, trust_level, section_kind, source_ref, heading, content`。
- `@dataclass(frozen=True) _Candidate`（line 84-93）：字段 `key:tuple[str,str], source_title, trust_level, section_kind, source_ref, heading, content, terms:frozenset[str]`。
- `CrossFeatureIndex.__init__(self, parsed_context)`（**同步**，line 99-123）：遍历 `parsed_context.sources`，仅收 `source.trust_level <= 2` 且 `section.section_kind in ("spec","summary")` 的 section，构建 `self._candidates: list[_Candidate]`。
- `CrossFeatureIndex.query(self, query_text, exclude_keys, *, top_k=3, min_score=_CROSS_MIN_SCORE)`（**同步**，line 125-157）：`_salient_terms(query)` → 对每个不在 `exclude_keys` 的候选算 `score = len(q & cand.terms)`，`score >= min_score` 入选 → 按 `(-score, source_ref)` 排序 → 返回 top_k 个 `GlobalSection`。

**调用点 1** — `src/testcase_generator/stages/write_cases/node.py`
- `async def generate_cases(...)`（line 224）内，line 323：`cross_index = CrossFeatureIndex(parsed_context)`；line 328：`for cs in cross_index.query(query_text, ctx_seen[fid], top_k=3):`。
- `settings` 导入：line 22 `from src.platform_api.core.settings import settings`（已有 `settings.cheat_sheet_injection_enabled` 等开关用法，line 209/387/402）。

**调用点 2** — `src/testcase_generator/stages/verify/node.py`
- `def _build_feature_sections(parsed_context, feature_ids, feature_query=None)`（**同步**，line 30）内，line 84：`cross_index = CrossFeatureIndex(parsed_context)`；line 89：`for cs in cross_index.query(q, seen[fid], top_k=3):`。
- `async def verify_node(...)`（line 102）内，line 142：`sections_by_feature = _build_feature_sections(parsed_context, feature_ids, dict(feature_query))`（**同步调用，改造后需 await**）。

**配置** — `src/platform_api/core/settings.py`
- 现有布尔开关样式（line 72-94）：`cheat_sheet_injection_enabled: bool = False` 等，pydantic settings，环境变量大写同名覆盖。

**测试目录** — `tests/testcase_generator/`（现有 `test_write_cases_cheat_sheet.py`、`test_write_cases_split.py`）。

**EmbeddingClient** — `src/knowledge_base/services/embedding/embedding_client.py`
- `EmbeddingClient()` 无参构造；`async embed_single(text) -> list[float]`；`async embed_batch(texts) -> list[list[float]]`（内部按 `_MAX_BATCH_SIZE=10` 分批）。空串返回 `[]`。

---

## File Structure

- **Modify** `src/platform_api/core/settings.py`：新增两个灰度配置项。
- **Modify** `src/testcase_generator/stages/context_utils.py`：`CrossFeatureIndex` 增加异步 `build()` 工厂、向量缓存、`query()` 改 async + Hybrid + RRF + 降级。
- **Modify** `src/testcase_generator/stages/write_cases/node.py`：调用点改 `await CrossFeatureIndex.build(...)` + `await cross_index.query(...)`。
- **Modify** `src/testcase_generator/stages/verify/node.py`：`_build_feature_sections` 改 async 并 await 调用链，`verify_node` 改为 `await _build_feature_sections(...)`。
- **Modify** `tests/testcase_generator/test_grounded_pipeline.py`：2 个旧同步 `CrossFeatureIndex` 测试改 `async def` + `await build/query`。
- **Create** `tests/testcase_generator/test_cross_feature_hybrid.py`：Hybrid 召回 / 开关关闭回退 / embedding 降级 三类测试。

> **重要约束**：`CrossFeatureIndex.query` 的返回类型、`GlobalSection` 字段、两个调用点对返回值的消费方式**保持不变**，下游 `feature_context` / `PrdSection` 注入逻辑零改动。本次只改「怎么召回」，不改「召回后怎么用」。

---

## Chunk 1: 灰度开关 + Hybrid 核心

### Task 1: 新增灰度配置项

**Files:**
- Modify: `src/platform_api/core/settings.py`（现有布尔开关聚集在 line 72-94 附近）

- [ ] **Step 1: 在 settings 中新增两个配置项**

在 `src/platform_api/core/settings.py` 里，紧挨现有 `cheat_sheet_injection_enabled: bool = False` 之后，新增：

```python
    # Hybrid 跨功能点规格检索（关键词 + 向量 + RRF）。
    # 关闭时 CrossFeatureIndex 行为与改造前完全一致（纯关键词，不调 embedding，零额外开销）。
    hybrid_cross_retrieval_enabled: bool = False
    # RRF 融合常数；候选集较小（数十~一两百）时可调到 20 锐化排名差异，默认 60 为业界稳健值。
    hybrid_cross_rrf_k: int = 60
```

- [ ] **Step 2: 验证配置可读**

Run:
```bash
uv run python -c "from src.platform_api.core.settings import settings; print(settings.hybrid_cross_retrieval_enabled, settings.hybrid_cross_rrf_k)"
```
Expected: 输出 `False 60`

- [ ] **Step 3: Commit**

```bash
git add src/platform_api/core/settings.py
git commit -m "feat(retrieval): 新增 hybrid 跨功能点检索灰度开关（默认关）"
```

---

### Task 2: CrossFeatureIndex 升级为 Hybrid（核心）

**Files:**
- Create: `tests/testcase_generator/test_cross_feature_hybrid.py`
- Modify: `src/testcase_generator/stages/context_utils.py`

**设计要点（实现时严格遵守）：**
- `CrossFeatureIndex.__init__` 保持同步、仅建关键词候选（`_candidates` 不变）。新增异步工厂 `@classmethod async def build(cls, parsed_context)`：先 `cls(parsed_context)`，再在开关开启且有候选时 `await self._ensure_embeddings()`（对所有候选 `content` 批量 embedding 并缓存 `self._cand_vectors`）。
- `query` 改 `async`。关键词路 = 现有词项重叠（产出有序候选列表 `kw_ranked`，保留 `min_score`、`exclude_keys`）。开关关或向量未就绪 → 直接返回 `kw_ranked[:top_k]`（与现状逐字节一致）。
- 开关开且向量就绪：`q_vec = await embed_single(query_text)`；向量路 = 对未被 `exclude_keys` 的候选算 cosine，降序得 `vec_ranked`（取候选池 `top_k*4` 即可）。两路用 RRF 融合（`1/(k+rank)` 累加，`k=settings.hybrid_cross_rrf_k`），返回融合后 `top_k`。
- 降级：`build` 期或 `query` 期任何 embedding 异常都 `logger.warning` 并回退纯关键词，**绝不抛出**。
- cosine 用纯 Python 实现（无 numpy 依赖假设）。

- [ ] **Step 1: 写失败测试**

创建 `tests/testcase_generator/test_cross_feature_hybrid.py`：

```python
"""CrossFeatureIndex Hybrid 检索测试：关键词盲区 / 向量补召回 / 异常降级。"""
from unittest.mock import patch

import pytest

from src.testcase_generator.stages import context_utils
from src.testcase_generator.stages.context_utils import CrossFeatureIndex


class _Sec:
    def __init__(self, heading, content, source_ref, section_kind="spec"):
        self.heading = heading
        self.content = content
        self.source_ref = source_ref
        self.section_kind = section_kind


class _Src:
    def __init__(self, title, trust_level, sections):
        self.title = title
        self.trust_level = trust_level
        self.sections = sections


class _Ctx:
    def __init__(self, sources):
        self.sources = sources


# A 与 query 词面重叠（"投放方式"）；B 语义相近但用词不同（"广告形式"），词面不重叠
_SEC_A = _Sec("投放方式切换规则", "切换投放方式后已选监测链接自动清空，需重新选择投放方式对应链接", "§6")
_SEC_B = _Sec("广告形式重置说明", "广告形式调整后追踪链接需重置", "§7")


def _ctx():
    return _Ctx([_Src("PRD", 1, [_SEC_A, _SEC_B])])


_QUERY = "切换投放方式后监测链接是否清空"


@pytest.mark.asyncio
async def test_disabled_is_keyword_only(monkeypatch):
    monkeypatch.setattr(context_utils.settings, "hybrid_cross_retrieval_enabled", False)
    idx = await CrossFeatureIndex.build(_ctx())
    res = await idx.query(_QUERY, set(), top_k=5, min_score=1)
    refs = {r.source_ref for r in res}
    assert "§6" in refs          # 词面重叠仍召回
    assert "§7" not in refs      # 纯关键词召不回语义相近的（这正是要修的盲区）


@pytest.mark.asyncio
async def test_hybrid_recalls_semantic_neighbor(monkeypatch):
    monkeypatch.setattr(context_utils.settings, "hybrid_cross_retrieval_enabled", True)

    async def fake_batch(self, texts):
        # 候选 A→[1,0,0]，候选 B→[0,1,0]
        return [[1.0, 0.0, 0.0] if "投放方式" in t else [0.0, 1.0, 0.0] for t in texts]

    async def fake_single(self, text):
        return [0.0, 0.95, 0.0]   # query 向量接近 B

    with patch.object(context_utils.EmbeddingClient, "embed_batch", fake_batch), \
         patch.object(context_utils.EmbeddingClient, "embed_single", fake_single):
        idx = await CrossFeatureIndex.build(_ctx())
        res = await idx.query(_QUERY, set(), top_k=5, min_score=1)
    refs = {r.source_ref for r in res}
    assert "§6" in refs and "§7" in refs   # 关键词召回A + 向量补召回B


@pytest.mark.asyncio
async def test_embed_failure_degrades_to_keyword(monkeypatch):
    monkeypatch.setattr(context_utils.settings, "hybrid_cross_retrieval_enabled", True)

    async def boom(self, *args, **kwargs):
        raise RuntimeError("embedding gateway down")

    with patch.object(context_utils.EmbeddingClient, "embed_batch", boom), \
         patch.object(context_utils.EmbeddingClient, "embed_single", boom):
        idx = await CrossFeatureIndex.build(_ctx())          # build 期失败不抛
        res = await idx.query(_QUERY, set(), top_k=5, min_score=1)
    refs = {r.source_ref for r in res}
    assert "§6" in refs                                       # 降级为纯关键词仍可用
```

- [ ] **Step 2: 运行测试，确认失败**

Run:
```bash
uv run pytest tests/testcase_generator/test_cross_feature_hybrid.py -v
```
Expected: FAIL —— `CrossFeatureIndex` 无 `build` 方法 / `query` 不是 async（`AttributeError` 或 `TypeError: object list can't be used in 'await'`）。

- [ ] **Step 3: 实现 Hybrid（修改 `context_utils.py`）**

3a. 顶部 import 区（现有 `import re` / `from dataclasses import dataclass` 附近）新增：

```python
import logging

from src.knowledge_base.services.embedding.embedding_client import EmbeddingClient
from src.platform_api.core.settings import settings

logger = logging.getLogger(__name__)
```

3b. 在 `_Candidate` dataclass 之后、`class CrossFeatureIndex` 之前，新增纯 Python cosine：

```python
def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)
```

3c. 用下面整段**替换**现有 `class CrossFeatureIndex`（原 line 96-157 整个类）。`__init__` 仅在末尾多了一行 `self._cand_vectors`，其余建候选逻辑保持不变：

```python
class CrossFeatureIndex:
    """全 PRD spec 章节索引；按测试点描述检索跨功能点参考章节。

    关键词路（词项重叠）始终可用；开启 settings.hybrid_cross_retrieval_enabled 时叠加
    向量路（候选 content embedding + cosine），RRF 融合，补召回语义相近但用词不同的章节。
    embedding 不可用时自动降级为纯关键词，绝不阻断生成。
    """

    def __init__(self, parsed_context) -> None:
        self._candidates: list[_Candidate] = []
        for source in parsed_context.sources:
            if source.trust_level > 2:  # 仅 PRD / 技术文档作为规格来源
                continue
            for section in source.sections:
                kind = getattr(section, "section_kind", "spec")
                if kind not in ("spec", "summary"):
                    continue
                key = (section.source_ref or "", section.heading or "")
                terms = _salient_terms((section.heading or "") + "\n" + (section.content or ""))
                if not terms:
                    continue
                self._candidates.append(
                    _Candidate(
                        key=key,
                        source_title=source.title,
                        trust_level=source.trust_level,
                        section_kind=kind,
                        source_ref=section.source_ref,
                        heading=section.heading,
                        content=section.content,
                        terms=frozenset(terms),
                    )
                )
        # 与 _candidates 同序的候选向量；None=未就绪（开关关 / embedding 失败）→ 走纯关键词
        self._cand_vectors: list[list[float]] | None = None

    @classmethod
    async def build(cls, parsed_context) -> "CrossFeatureIndex":
        """工厂：建关键词候选；开启 hybrid 时再异步算候选向量（失败自动降级）。"""
        self = cls(parsed_context)
        if settings.hybrid_cross_retrieval_enabled and self._candidates:
            await self._ensure_embeddings()
        return self

    async def _ensure_embeddings(self) -> None:
        try:
            texts = [(c.heading or "") + "\n" + (c.content or "") for c in self._candidates]
            vectors = await EmbeddingClient().embed_batch(texts)
            if len(vectors) == len(self._candidates):
                self._cand_vectors = vectors
            else:
                logger.warning(
                    "hybrid cross-retrieval: 候选向量数(%d)≠候选数(%d)，降级纯关键词",
                    len(vectors), len(self._candidates),
                )
                self._cand_vectors = None
        except Exception as exc:  # noqa: BLE001 — 任何 embedding 异常都降级，不阻断生成
            logger.warning("hybrid cross-retrieval: 候选 embedding 失败，降级纯关键词: %s", exc)
            self._cand_vectors = None

    def _keyword_ranked(
        self, query_text: str, exclude_keys: set[tuple[str, str]], min_score: int
    ) -> list[_Candidate]:
        q = _salient_terms(query_text)
        if not q:
            return []
        scored: list[tuple[int, _Candidate]] = []
        for cand in self._candidates:
            if cand.key in exclude_keys:
                continue
            score = len(q & cand.terms)
            if score >= min_score:
                scored.append((score, cand))
        scored.sort(key=lambda t: (-t[0], t[1].source_ref))
        return [cand for _score, cand in scored]

    def _vector_ranked(
        self, q_vec: list[float], exclude_keys: set[tuple[str, str]], pool: int
    ) -> list[_Candidate]:
        scored: list[tuple[float, _Candidate]] = []
        for cand, vec in zip(self._candidates, self._cand_vectors or []):
            if cand.key in exclude_keys:
                continue
            scored.append((_cosine(q_vec, vec), cand))
        scored.sort(key=lambda t: (-t[0], t[1].source_ref))
        return [cand for _s, cand in scored[:pool]]

    def _to_sections(self, cands: list[_Candidate]) -> list[GlobalSection]:
        return [
            GlobalSection(
                source_title=c.source_title,
                trust_level=c.trust_level,
                section_kind=c.section_kind,
                source_ref=c.source_ref,
                heading=c.heading,
                content=c.content,
            )
            for c in cands
        ]

    async def query(
        self,
        query_text: str,
        exclude_keys: set[tuple[str, str]],
        *,
        top_k: int = 3,
        min_score: int = _CROSS_MIN_SCORE,
    ) -> list[GlobalSection]:
        """关键词召回；hybrid 开启且向量就绪时叠加向量召回 + RRF 融合，返回 top_k。"""
        kw_ranked = self._keyword_ranked(query_text, exclude_keys, min_score)

        # 纯关键词单路：开关关 / 向量未就绪 → 与改造前逐字节一致
        if not (settings.hybrid_cross_retrieval_enabled and self._cand_vectors):
            return self._to_sections(kw_ranked[:top_k])

        try:
            q_vec = await EmbeddingClient().embed_single(query_text)
        except Exception as exc:  # noqa: BLE001 — query embedding 失败也降级
            logger.warning("hybrid cross-retrieval: query embedding 失败，降级纯关键词: %s", exc)
            return self._to_sections(kw_ranked[:top_k])

        if not q_vec:
            return self._to_sections(kw_ranked[:top_k])

        vec_ranked = self._vector_ranked(q_vec, exclude_keys, pool=max(top_k * 4, 12))

        # RRF 融合（按 rank，不混用原始分；k 越小越锐化）
        k = settings.hybrid_cross_rrf_k
        scores: dict[tuple[str, str], float] = {}
        cand_by_key: dict[tuple[str, str], _Candidate] = {}
        for rank, cand in enumerate(kw_ranked):
            scores[cand.key] = scores.get(cand.key, 0.0) + 1.0 / (k + rank + 1)
            cand_by_key[cand.key] = cand
        for rank, cand in enumerate(vec_ranked):
            scores[cand.key] = scores.get(cand.key, 0.0) + 1.0 / (k + rank + 1)
            cand_by_key[cand.key] = cand

        fused = sorted(scores, key=lambda key: (-scores[key], cand_by_key[key].source_ref))
        return self._to_sections([cand_by_key[key] for key in fused[:top_k]])
```

> 说明：关键词路保留 `min_score` 噪声下限；向量路不受 `min_score` 限制（这正是它补召回「词面分低但语义相近」章节的价值），但只取 `pool` 候选再交给 RRF，避免噪声灌入。

- [ ] **Step 4: 运行测试，确认通过（含旧测试兼容）**

Run:
```bash
uv run pytest tests/testcase_generator/ -q
```
Expected: 全绿。`query` 改 async 后，`test_grounded_pipeline.py` 中 2 个旧同步调用会 `TypeError: 'coroutine' object is not iterable`——需同步修改为 `async def` + `await build/query`（见 File Structure），一并在本步验证通过。

- [ ] **Step 5: Commit**

```bash
git add src/testcase_generator/stages/context_utils.py tests/testcase_generator/test_cross_feature_hybrid.py
git commit -m "feat(retrieval): CrossFeatureIndex 升级 hybrid（关键词+向量+RRF），灰度+降级"
```

---

## Chunk 2: 两个调用点改异步

### Task 3: write_cases 调用点改 await

**Files:**
- Modify: `src/testcase_generator/stages/write_cases/node.py`（`generate_cases` 内，原 line 323 与 328）

- [ ] **Step 1: 改构造与查询为 await**

把（原 line 323）：
```python
    cross_index = CrossFeatureIndex(parsed_context)
```
改为：
```python
    cross_index = await CrossFeatureIndex.build(parsed_context)
```

把（原 line 328）：
```python
        for cs in cross_index.query(query_text, ctx_seen[fid], top_k=3):
```
改为：
```python
        for cs in await cross_index.query(query_text, ctx_seen[fid], top_k=3):
```

> `generate_cases` 已是 `async def`（line 224），可直接 await；返回值结构与下游 `feature_context` 注入逻辑零改动。

- [ ] **Step 2: 跑 write_cases 相关测试 + 全量 testcase_generator 回归**

Run:
```bash
uv run pytest tests/testcase_generator/ -q
```
Expected: 全绿（含改造前已存在的 `test_write_cases_*`）。开关默认关，行为应与改造前一致。

- [ ] **Step 3: Commit**

```bash
git add src/testcase_generator/stages/write_cases/node.py
git commit -m "refactor(write-cases): 跨章节检索改用 await CrossFeatureIndex.build/query"
```

---

### Task 4: verify 调用链改 async

**Files:**
- Modify: `src/testcase_generator/stages/verify/node.py`（`_build_feature_sections` line 30 起；`verify_node` line 142）

- [ ] **Step 1: `_build_feature_sections` 改 async + 内部 await**

把函数签名（line 30）：
```python
def _build_feature_sections(
    parsed_context: ParsedContext,
    feature_ids: set[str],
    feature_query: dict[str, str] | None = None,
) -> dict[str, list[PrdSection]]:
```
改为：
```python
async def _build_feature_sections(
    parsed_context: ParsedContext,
    feature_ids: set[str],
    feature_query: dict[str, str] | None = None,
) -> dict[str, list[PrdSection]]:
```

把函数体内（原 line 84）：
```python
        cross_index = CrossFeatureIndex(parsed_context)
```
改为：
```python
        cross_index = await CrossFeatureIndex.build(parsed_context)
```

把（原 line 89）：
```python
            for cs in cross_index.query(q, seen[fid], top_k=3):
```
改为：
```python
            for cs in await cross_index.query(q, seen[fid], top_k=3):
```

- [ ] **Step 2: `verify_node` 调用处加 await**

把（line 142）：
```python
    sections_by_feature = _build_feature_sections(parsed_context, feature_ids, dict(feature_query))
```
改为：
```python
    sections_by_feature = await _build_feature_sections(parsed_context, feature_ids, dict(feature_query))
```

> 全仓搜索确认 `_build_feature_sections` 仅此一处调用（`verify_node` 内）。若搜索发现其它调用点，一并加 `await`。

- [ ] **Step 3: 验证无其它同步调用残留**

Run:
```bash
rg -n "_build_feature_sections\(" src/ tests/
```
Expected: 仅 `verify/node.py` 内的定义与（已加 await 的）调用；无其它裸调用。

- [ ] **Step 4: 跑相关测试**

Run:
```bash
uv run pytest tests/testcase_generator/ -q
```
Expected: 全绿。

- [ ] **Step 5: Commit**

```bash
git add src/testcase_generator/stages/verify/node.py
git commit -m "refactor(verify): _build_feature_sections 改 async 以支持 hybrid 检索"
```

---

## Chunk 3: 灰度验证与收尾

### Task 5: 灰度 A/B 验证（不改代码，验证质量杠杆是否生效）

**目的：** 证明 hybrid 确实补召回了纯关键词漏掉的跨章节规格，从而减少「需求待确认」空壳。

- [ ] **Step 1: 全量回归（开关默认关，确认零回归）**

Run:
```bash
uv run pytest tests/ -q
```
Expected: 全绿（开关关时行为与改造前一致）。

- [ ] **Step 2: 准备 A/B 对照（同一文档、各跑一次生成）**

- 关组：保持 `.env` 不设或 `HYBRID_CROSS_RETRIEVAL_ENABLED=false`，对某文档触发一次生成，记录批次 B_off。
- 开组：`.env` 设 `HYBRID_CROSS_RETRIEVAL_ENABLED=true`，重启 worker 后对**同一文档**再触发一次生成，记录批次 B_on。

> 开关读取见 `settings.hybrid_cross_retrieval_enabled`；环境变量名大写同名 `HYBRID_CROSS_RETRIEVAL_ENABLED`。改 `.env` 后必须重启 Celery worker 才生效。

- [ ] **Step 3: 对比两项指标**

```bash
# 「需求待确认」空壳率（标题以【需求待确认】开头的占比），分别对 B_off / B_on 跑：
docker exec qa-platforms-pg psql -U postgres -d qa_platforms -c "SELECT '<BATCH_ID>' AS batch, round(100.0*sum(CASE WHEN title LIKE '【需求待确认】%' THEN 1 ELSE 0 END)/count(*),1) AS pending_clarify_pct, count(*) AS total FROM testcase.test_cases WHERE batch_id='<BATCH_ID>';"
```
Expected: B_on 的 `pending_clarify_pct` ≤ B_off（hybrid 补召回深层规格 → 更少误判留白）。若持平或更差，记录到 `findings.md` 供进一步调 `hybrid_cross_rrf_k`（候选少时试 20）或 `pool` 大小。

- [ ] **Step 4: 验证日志中 hybrid 生效 / 未异常降级**

Run（生成期间观察 worker 日志）:
```bash
rg -n "hybrid cross-retrieval" <worker 日志或终端输出>
```
Expected: **无** "降级纯关键词" 警告（若有，说明 embedding 调用异常，需排查网关/批大小后重试）。

---

## 总验收标准（全部满足才算完成）

- [ ] Task 1–4 提交齐全，`uv run pytest tests/ -q` 全绿。
- [ ] 开关关：`tests/testcase_generator/` 全量通过，行为与改造前一致（无回归）。
- [ ] 开关开：`test_cross_feature_hybrid.py` 3 项通过（纯关键词盲区 / 向量补召回 / 异常降级）。
- [ ] `GlobalSection` 字段、`query` 返回结构、两个调用点对返回值的消费方式均未变（下游零改动）。
- [ ] `rg -n "_build_feature_sections\(" src/` 无遗漏的同步调用。
- [ ] `uv run ruff check src/platform_api/core/settings.py src/testcase_generator/stages/context_utils.py src/testcase_generator/stages/verify/node.py` 通过；`write_cases/node.py` 确认未新增 lint（历史 E501 不计入）。
- [ ] A/B 对照已记录（B_on 空壳率 ≤ B_off，或已记录待调参）。

## 风险与回退

- **噪声风险**：向量路可能召回弱相关章节。缓解：关键词路保留 `min_score` 下限、向量路只取 `pool` 候选、RRF 抑制单路独大；必要时调小 `hybrid_cross_rrf_k`。
- **延迟/成本**：每个 batch 多一次候选批量 embedding + 每 feature 一次 query embedding。缓解：候选向量在 `build()` 时算一次并缓存；灰度默认关，按需开启。
- **即时回退**：`HYBRID_CROSS_RETRIEVAL_ENABLED=false`（或删除该环境变量）+ 重启 worker，**零代码回滚**到纯关键词。
- **不波及面**：`document_embeddings` 表与既有向量检索服务（`VectorSearchService` 等）本次完全不动。

## 执行说明（给 Claude Code）

- 本计划用 `superpowers:executing-plans` 执行：逐 Task 按 checkbox 步骤做，跑每步验证命令，绿了再 commit、再下一步。
- 数据库为 docker 容器 `qa-platforms-pg`；后端/worker 启停命令见 `CLAUDE.md`。改 `.env` 开关后需重启 worker。
- 任一步骤验证失败或指令不清，**停下来问**，不要猜着往下做。
- 严格保持「只改怎么召回、不改召回后怎么用」：不得改动 `GlobalSection` 字段或下游 `feature_context`/`PrdSection` 注入逻辑。

