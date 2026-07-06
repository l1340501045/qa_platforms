# 语义去重升级（③）GPT Review 复核记录 — 交接 Claude Code

> **用途**：本次对话（2026-06-30）对 roadmap ③「语义去重升级」实施计划的 GPT Review + 修复复核存档。供后续 Claude Code 了解背景、避免重复劳动、并接手唯一遗留项。
> **关联**：roadmap `docs/2026-06-30-quality-alignment-roadmap.md` ③ ／ spec `docs/spec/2026-06-30-semantic-dedup-design.md` ／ plan `docs/plans/2026-06-30-semantic-dedup-plan.md`
> **分支**：`feat/architecture-migration`（6 commits：原 5 + 修复 1）

---

## TL;DR

- ③ 语义去重的 Review 共 **5 条意见（1 🔴 + 4 🟡），已全部修复并经独立复核通过 ✅**。
- 复核证据：按计划口径（排除 integration）`262 passed`；`ruff All checks passed`；6 个提交文件隔离干净（零计划外文件）。
- **唯一遗留（非本次引入，待后续处理）**：integration 测试 `test_nogo_resume_not_deadloop` 红灯——大概率是「测试过期」（澄清流程改版后老测试没跟），属 ①②④ 澄清/冲突线，**不归 ③**。
- **③ 本身无待办**，可推进 roadmap 下一项（④ 同实体门控）。

---

## 一、Review 对象

给 `find_duplicates` 增加**语义相似层**（embedding cosine），抓词面去重抓不到的「换措辞同义」近重复，灰度可回退、关时零回归、纯函数可离线单测。涉及文件：

- `src/testcase_generator/stages/dedup/clustering.py`（`find_duplicates` 加 `embeddings` 入参 + 语义 pass）
- `src/testcase_generator/stages/dedup/node.py`（async 算向量传入 + 灰度 + 失败降级）
- `src/platform_api/core/settings.py`（`semantic_dedup_enabled` / `_threshold` / `_cross_tp_threshold`）
- `tests/testcase_generator/test_semantic_dedup.py`（纯函数 TDD + 护栏 + 零回归）
- `scripts/dedup_offline_eval.py`（3185 条离线压缩率评估）

---

## 二、Review 发现与修复（全部已闭环，均在 commit `25b3d23`）

| 编号 | 问题 | 修复 | 验证证据 |
|---|---|---|---|
| 🔴-1 | 语义 pass 中 `same_tp = bool(c.feature_id) and ...` 误引用**循环外残留变量** `c`（= `cases[-1]`）。导致「同 tp / 跨 tp」阈值判定取决于「最后一条输入用例是否带 test_point_id」这一无关状态，**破坏可复现性**（锁定硬约束）。 | 改为基于当前对自身：`same_tp = bool(feature_of[a]) and feature_of[a] == feature_of[b]`（`clustering.py:236`），并加注释禁止引用循环外变量。 | 运行复现：仅改末条无关用例 `feature_id` 是否为空，同 tp、cosine=0.88 的 A/B 折叠结果即从「不折叠」翻转为「折叠」。修复后新增 2 个回归测试精确卡边界（见下）。 |
| 🟡-1 | plan 中 `semantic_dedup_cross_tp_threshold` 三处口径不一致（File Structure 漏列、Task 4 Step 2 传参漏传），靠默认值 0.90 侥幸不出错。 | plan File Structure(行27)、Task 4 Step 2(行109)、Task 2 Step 3(行77) 三处补齐统一。代码 `node.py:87` 实际已正确传参。 | 重读 plan 三处一致；`node.py` 传 `semantic_cross_tp_threshold=settings.semantic_dedup_cross_tp_threshold`。 |
| 🟡-2 | 「关时逐字节一致」是硬约束，但验证仅靠几个手写小用例，无规模化对拍。 | 新增 `test_zero_regression_offline_golden`：3185 条不传 embeddings → `dup_count==228`（golden）；`.audit` 缺失则 skip。 | 测试通过；228 为改造前纯词面基线值。 |
| 🟡-3 | 降级测试用词面差异大的对，无法区分「降级到词面」与「去重整段被跳过」。 | 新增 `test_dedup_node_degrades_to_lexical_and_lexical_still_folds`：embedding 失败后，一对**词面能折叠**的用例仍被折叠（`TC-002→TC-001`，`count==1`）。 | 测试通过，真正证明「降级到词面」。 |
| 🟡-4 | 语义 pass 行内 `if s < 1.0 - 1e-12 and s < semantic_threshold` 前半段冗余 + 误导注释；plan「禁止纯 python 双循环」措辞与实现（矩阵化后 python 遍历上三角）字面冲突。 | 简化为 `if s < semantic_threshold: continue`（`clustering.py:227`），删误导注释；plan 措辞改为「禁止在双循环内**计算 cosine**」。 | 重读 `clustering.py:227` 已简化；plan Task 2 Step 3 措辞已澄清。 |

**🔴-1 新增回归测试（2 个，互补卡边界）：**
- `test_semantic_same_tp_not_polluted_by_trailing_empty_feature`：末条 `feature_id` 空 + 同 tp、cosine=0.878∈[0.86,0.90) → **应折叠**（用 0.86，不被末条污染成 0.90）。修复前必 FAIL，修复后 PASS，是 bug 的精确捕获器。
- `test_semantic_trailing_empty_feature_does_not_collapse_cross_tp_pair`：同场景但跨 tp → **仍不折叠**（跨 tp 用 0.90 严阈值，防修复过度放松）。

---

## 三、复核结论（独立验证，非纸面）

| 项 | 结果 |
|---|---|
| 测试（计划口径，排除 integration）`uv run pytest tests/testcase_generator/ -q --ignore=tests/testcase_generator/integration` | `262 passed` ✅ |
| 测试（完整 `tests/testcase_generator/`） | `268 passed, 1 failed, 3 skipped`——1 failed 为遗留项（见第四节），与 ③ 无关 |
| ruff（改动文件） | `All checks passed!` ✅ |
| 提交隔离 | 6 commits 文件汇总仅含 clustering/node/settings/test_semantic_dedup/eval/roadmap/plan，**零计划外文件** ✅ |

**提交清单（`feat/architecture-migration`）：**
```
25b3d23 fix(dedup): GPT Review 修复 same_tp 循环外变量泄漏 + 补 3 回归测试   ← 本次 Review 修复
c834199 feat(dedup): 离线评估脚本 + roadmap ③ 进度（3185→1691，抽样 7/10 真同义）
3abb4d6 feat(dedup): dedup_node 算 embedding 传入 + 失败降级纯词面（灰度 semantic_dedup_enabled）
e2ae4d0 feat(settings): 加 semantic_dedup 灰度开关 + 阈值（默认关，零回归）
80d1d6e feat(dedup): find_duplicates 加语义候选（embedding cosine，护栏全复用，关时零回归）
3099967 test(dedup): find_duplicates 零回归基线（不传 embeddings 行为不变）
```

**已知特性（非缺陷，知悉即可）：**
- `test_zero_regression_offline_golden` 依赖 `.audit/278c211f-.../` 这批 **untracked 审计数据**，CI/新克隆环境会 skip。即 228 这道零回归防线只在本地生效，CI 上零回归仍靠 Task 1 手写小用例守护。

---

## 四、遗留待办（待 Claude Code 处理）

### [优先级：低，不阻塞 ③] integration 测试 `test_nogo_resume_not_deadloop` 红灯

**位置**：`tests/testcase_generator/integration/test_full_pipeline.py::test_nogo_resume_not_deadloop`

**现象**：模拟「comprehend 判 NO_GO → 用户提供 `clarification_answers` → 第二次 comprehend 应转 GO/CONDITIONAL」，但第二次 `understanding_coverage` 仍为 0.15（NO_GO），断言失败（“死循环”）。

**已查证（本次对话结论）**：
- **与 ③ 语义去重无关**：本次 6 提交文件清单与 comprehend/pipeline **零交集**。
- **非在途改动引入**：`src/testcase_generator/stages/comprehend`、`tests/.../integration`、`src/testcase_generator/pipeline` 路径**无任何未提交改动**。
- **大概率是「测试过期」**：`comprehend/node.py:173` 注释明确写「**方案 A 后澄清不再回 comprehend；此函数仅首次理解使用**」。即澄清处理已改道至独立节点 `comprehend/apply_clarification.py`，而该测试仍在验证「第二次 comprehend 读澄清→GO」这条**已废弃的旧路径**。测试 mock 按旧 prompt 格式找 `"clarification_answers" in input_data`，自然命中失败。

**建议给 Claude Code 的处理方式**（择机，建议并入 ①②④ 澄清/冲突线时顺手做）：
1. 先确认**真实** resume 流程现状：NO_GO → interrupt → `apply_clarification.py` 是否正确消费 `clarification_answers` 并提升覆盖/转 GO（即「问→答→继续」真实可用，不死循环）。
2. 若真实流程 OK（预期）→ 把 `test_nogo_resume_not_deadloop` **迁移/改写**到新的 `apply_clarification` 路径上，删除对旧 comprehend-重判 路径的断言。
3. 若真实流程也断 → 升级为真 bug 修复（澄清答案未被新路径正确消费）。
4. 顺带核查 `comprehend/node.py` 中残留的 `clarification_answers` 读取逻辑（行101/107-108）是否为应清理的死代码。

**范围归属**：①②④ 澄清/冲突线（roadmap `docs/2026-06-30-quality-alignment-roadmap.md`），非 ③。

---

## 五、下一步

- ③ 已闭环，可推进 **④ 同实体门控**（plan 已就绪：`docs/plans/2026-06-30-conflict-entity-gate-plan.md`，roadmap 标「待交 Claude Code」）。
- 遗留红灯择机处理（见第四节）。
- ③ 真实压缩率/阈值标定：离线 hybrid 已压到 unique 1691（46.9%），抽样 7/10 真同义、3 误折叠（含 1 边界值对）。误折叠靠软标记 `duplicate_of` 可恢复 + 生产 `safe_dedup` 护栏兜底；若最终大 PRD 验收发现偏松，可上调 `semantic_dedup_threshold`（当前 0.86）。
