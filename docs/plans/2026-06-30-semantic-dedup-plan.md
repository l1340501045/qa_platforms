# 语义去重升级（hybrid embedding + 词法）Implementation Plan

> **For agentic workers:** REQUIRED: 用 superpowers:executing-plans 执行；步骤用 `- [ ]` 勾选跟踪。
> 关联 spec：`docs/spec/2026-06-30-semantic-dedup-design.md`。

**Goal:** 给 `find_duplicates` 增加**语义相似层**（embedding cosine）抓"换措辞同义"近重复，预期 3185→~2000；**全程保留现有护栏、灰度可回退、关时逐字节现状**；`find_duplicates` 保持纯同步可离线单测（向量外部算好传入）。

**Architecture:** `find_duplicates` 加可选 `embeddings` 入参 → 在词面候选外**额外**生成语义候选（分组内 cosine≥阈值），候选同样过 `_protected`+`safe_dedup` 护栏后 `_union`。`dedup_node`(async) 算向量传入、灰度、失败降级。embedding 不进纯函数。

**Tech Stack:** Python 3.12 / numpy / pydantic / pytest（asyncio_mode=auto）/ 现有 `EmbeddingClient`。

---

## 现状速查（对齐当前代码）

- `stages/dedup/clustering.py`：`DedupCase`(行33-44，字段 case_id/feature_id(=test_point_id)/title/text/is_placeholder/dimension/rule_codes)；`find_duplicates`(行60-203)；`_union`+safe_dedup 护栏(行95-113)；`_protected` 边界保护(行144-146)；词面候选 bigram 倒排(行167-195)；输出 dup_map(行198-203)。**注释行13"不依赖外部 embedding"——本计划用灰度+外部传入向量保此性质。**
- `stages/dedup/node.py`：`dedup_node`(async)；构造 `DedupCase`、调 `find_duplicates(..., safe_dedup_enabled=settings.safe_dedup_enabled)`；`return {"final_test_cases":..., "dedup_summary":...}`。
- `knowledge_base/services/embedding/vectorize_pipeline.py:54`：`await self.embedding_client.embed_batch(texts)`；`EmbeddingClient` 无参构造。
- `core/settings.py`：灰度开关区（`safe_dedup_enabled` 等）。
- **mock 约定**：`monkeypatch.setattr(mod, "EmbeddingClient", FakeClient)`；纯函数测试传固定向量、不调网络。
- **⚠️ 提交隔离**：工作树有大量其他未提交改动。每个 Task 只 `git add` 本计划列出文件，**严禁 `-A`/`git add .`**。

## File Structure

- **Modify** `src/testcase_generator/stages/dedup/clustering.py`（`find_duplicates` 加 `embeddings` 入参 + 语义候选；新增 `_cosine` 纯函数）
- **Modify** `src/testcase_generator/stages/dedup/node.py`（算向量传入 + 灰度 + 降级）
- **Modify** `src/platform_api/core/settings.py`（`semantic_dedup_enabled` + `semantic_dedup_threshold` + `semantic_dedup_cross_tp_threshold`）
- **Create** `tests/testcase_generator/test_semantic_dedup.py`（纯函数 TDD + 护栏 + 零回归）
- **Create** `scripts/dedup_offline_eval.py`（现有 3185 条离线压缩率评估，仅评估用）

---

## Chunk 1: find_duplicates 加语义候选（纯函数 TDD，传固定向量）

### Task 1: 零回归基线 —— 不传 embeddings 行为不变

**Files:** Create `tests/testcase_generator/test_semantic_dedup.py`

- [ ] **Step 1: 写测试**——一组 `DedupCase`，分别 `find_duplicates(cases)`（不传 embeddings）断言 dup_map 与现状一致（覆盖词面折叠 + 边界 `_protected` + safe_dedup 护栏）。
- [ ] **Step 2: 跑通**（绿——这是改造前基线）
Run: `uv run pytest tests/testcase_generator/test_semantic_dedup.py -v`
- [ ] **Step 3: Commit**
```bash
git add tests/testcase_generator/test_semantic_dedup.py
git commit -m "test(dedup): find_duplicates 零回归基线（不传 embeddings 行为不变）"
```

### Task 2: 加 `embeddings` 入参 + 语义候选（TDD）

**Files:** `clustering.py`、Test 同文件

- [ ] **Step 1: 写失败测试**——两条**词面差异大、向量高度相似**的同义用例（传固定 embeddings，cosine≈0.95），断言被折叠；另写两条**向量相似但数字集不同+含边界关键词**的（"最多1000行" vs "最多999行"），断言 `_protected` **仍保护、不折叠**；再写"safe_dedup 下语义候选不删某规则最后一条"。**另补 🔴-1 回归用例**：末条 case `feature_id` 为空 + 一对同 tp、cosine∈[0.86,0.90) 的对，断言应折叠（验证同 tp 用 0.86 而非被末条状态污染成 0.90）；互补断言跨 tp 同 cosine 区间不折叠。
```python
def _emb(*vals): return list(vals)  # 简化：低维固定向量，cosine 可控

def test_semantic_folds_cross_testpoint_synonyms():
    # 跨 test_point 的换措辞同义（灌水大头）——语义候选须"全局"，不能只在组内
    a = DedupCase(case_id="A", feature_id="TP1", title="组长可查看全员定向包", dimension="access_control")
    b = DedupCase(case_id="B", feature_id="TP2", title="投放组长能看到所有成员创建的定向包", dimension="access_control")
    emb = {"A": _emb(1.0, 0.0), "B": _emb(0.985, 0.02)}  # cosine≈0.999
    dup = find_duplicates([a, b], embeddings=emb,
                          semantic_threshold=0.86, semantic_cross_tp_threshold=0.90)
    assert dup.get("B") == "A" or dup.get("A") == "B"

def test_semantic_respects_boundary_protection():
    a = DedupCase(case_id="A", feature_id="TP1", title="最多1000行", text="上限1000")
    b = DedupCase(case_id="B", feature_id="TP1", title="最多999行", text="上限999")
    emb = {"A": _emb(1.0, 0.0), "B": _emb(1.0, 0.0)}  # cosine=1 但边界保护应拦下
    dup = find_duplicates([a, b], embeddings=emb, semantic_threshold=0.86)
    assert dup == {}  # _protected 生效，不折叠
```
- [ ] **Step 2: 跑失败** → FAIL（无 embeddings 参数）。
- [ ] **Step 3: 实现**——
  - `find_duplicates` 签名加 `embeddings: dict[str, list[float]] | None = None`、`semantic_threshold: float = 0.86`、`semantic_cross_tp_threshold: float = 0.90`。
  - 在词面 pass（行166-195）**之后**加语义 pass（embeddings 为 None 整段跳过）：
    - **全局**（非仅组内——灌水大头是跨 tp/跨模块换措辞重复）用 **numpy 矩阵化** 算 cosine：按 case 顺序堆叠有向量的 case 成矩阵 `M`、L2 归一化、`S = M @ M.T`，取上三角 `i<j` 超阈值对。**禁止在双循环内逐对计算 cosine**（3185²×D 太慢）；矩阵化得 `S` 后用 python 遍历上三角索引（O(n²) 纯索引比较、无 D 维运算）取候选对可接受。
    - 阈值：`同 feature_id → semantic_threshold(0.86)`；`跨 feature_id → semantic_cross_tp_threshold(0.90)`（仿词面"跨维严/同维松"，控误折叠）。**⚠️ `same_tp` 必须基于当前对 (a,b) 自身的 `feature_of[a]/feature_of[b]` 判定，禁止引用循环外变量**（GPT Review 🔴-1：落地曾误用上文 `for c in cases` 残留的 `c.feature_id`，导致折叠结果依赖无关末条用例，破坏确定性）。防错写法：`same_tp = bool(feature_of[a]) and feature_of[a] == feature_of[b]`。
    - 每个超阈值对：**非 `_protected`** 才 `_union(a,b)`（`_union` 内已含 safe_dedup 护栏，自动复用）。`_protected` 对所有候选对统一判定（含 cosine=1 的同向量边界值对），无需为 s≈1 特殊分支。
    - 缺向量的 case（embeddings 无该 case_id）跳过。
- [ ] **Step 4: 跑通 + Task1 基线仍绿**
Run: `uv run pytest tests/testcase_generator/test_semantic_dedup.py -v`
- [ ] **Step 5: Commit**
```bash
git add src/testcase_generator/stages/dedup/clustering.py tests/testcase_generator/test_semantic_dedup.py
git commit -m "feat(dedup): find_duplicates 加语义候选（embedding cosine，护栏全复用，关时零回归）"
```

---

## Chunk 2: settings 开关 + node 接入（async 算向量 + 降级）

### Task 3: settings 加灰度开关

**Files:** `core/settings.py`

- [ ] **Step 1**：加 `semantic_dedup_enabled: bool = False` + `semantic_dedup_threshold: float = 0.86`（同 test_point）+ `semantic_dedup_cross_tp_threshold: float = 0.90`（跨 test_point，更严）（注释：依赖 safe_dedup_enabled 开时才建议启用）。
- [ ] **Step 2: 冒烟**
Run: `uv run python -c "from src.platform_api.core.settings import settings; print(settings.semantic_dedup_enabled, settings.semantic_dedup_threshold)"`
Expected: `False 0.86`。
- [ ] **Step 3: Commit**（只 add settings.py）。

### Task 4: dedup_node 算向量传入 + 降级（TDD）

**Files:** `stages/dedup/node.py`、Test 同测试文件

- [ ] **Step 1: 写测试**——mock `EmbeddingClient` 返回固定向量，`semantic_dedup_enabled=True` 时 `dedup_node` 把向量传入 `find_duplicates`（断言语义折叠生效）；mock 抛异常时**降级**为纯词面（断言不抛、dedup_summary 仍产出）。**🟡-3 补充**：降级测试须用一对**词面能折叠**的用例，断言 embedding 失败时仍被词面 pass 折叠（证明是"降级到词面"而非"去重被跳过"）。
- [ ] **Step 2: 跑失败 → 实现**——
  - `semantic_dedup_enabled` 时：`texts=[c.title + " " + " ".join(c.expected_results or []) for c in final_cases]`；`try: embs = await EmbeddingClient().embed_batch(texts); embeddings={cid: v ...} except Exception: logger.warning(降级); embeddings=None`。
  - 传 `find_duplicates(..., embeddings=embeddings, semantic_threshold=settings.semantic_dedup_threshold, semantic_cross_tp_threshold=settings.semantic_dedup_cross_tp_threshold)`。
  - 关时 `embeddings=None`（现状）。
- [ ] **Step 3: 跑通 + 全量回归**
Run: `uv run pytest tests/testcase_generator/ -q --ignore=tests/testcase_generator/integration`
- [ ] **Step 4: ruff + Commit**（add node.py + 测试）。

---

## Chunk 3: 离线压缩率评估（用现有 3185 条，≈0 成本）

### Task 5: `dedup_offline_eval.py`

**Files:** Create `scripts/dedup_offline_eval.py`

- [ ] **Step 1**：读 `.audit/<batch>/modules/*.cases.jsonl` → 构造 `DedupCase`（**自审注：导出用例 JSON 无 rule_id，离线 `rule_codes` 缺失 → safe_dedup 护栏在离线评估中退化；护栏真实性以 Chunk 1 单测为准，本脚本主评"语义折叠召回 + 误折叠抽查"**）→ 算向量（`EmbeddingClient.embed_batch`）→ 跑 `find_duplicates`（语义开/关各一次）→ 打印：duplicate 数、唯一数、压缩率、随机抽 10 个语义折叠对供人工判真伪。
- [ ] **Step 2: 运行**（成本仅 embedding，分钱级）
Run: `uv run python scripts/dedup_offline_eval.py 278c211f-6f25-4970-a425-9db94cbc8ff7`
Expected：语义开启后 duplicate 数显著 > 263、总量压到 ~2000；抽样折叠对多为真同义。
- [ ] **Step 3**：把前后对照（词面-only vs hybrid 压缩率 + 抽样判真）记入 roadmap ③ 进度。
- [ ] **Step 4: Commit**（只 add scripts/dedup_offline_eval.py）。

---

## 总验收标准

- [ ] 不传 `embeddings` / 关 `semantic_dedup_enabled` → `find_duplicates` 与改造前逐字节一致（Task 1 基线绿 + 🟡-2 离线 3185 条 golden 对拍 dup_count==228 稳定）。
- [ ] 语义候选能折叠"词面远、语义近"的同义对（Task 2）。
- [ ] 边界值 `_protected`、safe_dedup"规则最后一条"对语义候选**仍生效**（Task 2）。
- [ ] dedup_node 降级安全：embedding 失败不阻断、退纯词面（Task 4）。
- [ ] 离线评估：hybrid 压缩到 ~2000、抽样折叠对为真同义（Task 5）。
- [ ] 全量（排除 integration）回归绿；ruff 干净；提交仅含本计划文件。

## 风险与回退

- **语义误折叠** → `_protected` + 保守阈值 0.86 + 软标记可恢复（`duplicate_of`，不硬删）+ Task 5 抽样人工判；回退即关 `semantic_dedup_enabled`。
- **破坏可复现/离线** → 向量外部算、传入纯函数；关开关零回归；单测用固定向量不触网。
- **O(n²) 规模** → 优先分组（feature/test_point）内两两；3185 全局 numpy 也可接受；量大 future LSH（不在本计划）。
- **提交污染** → 每 Task 仅 `git add` 指定文件，绝不 `-A/.`。
