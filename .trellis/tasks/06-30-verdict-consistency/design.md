# 同构同判 verdict 判级一致性设计

## 背景

当前 `verify_cases` 对每条用例做单次 LLM judge，`_verify_batch` 内已有同实体门控会把概念混淆类假 conflict 降级，但聚合结果后没有跨条一致化。同一 feature 下高度同构的用例可能出现 `grounded`、`ungrounded`、`conflict` 分裂，导致最终质量报告不稳定。

## 设计目标

- 5a：在 `verify_cases` 聚合后做确定性判后一致化，零 LLM 成本、可单测、可离线评估。
- 5b：对首轮 conflict 子集做灰度复判，用多数票降低单次误判抖动。
- 保证默认关闭时零行为变化。
- 保证 5a 不撤销已有同实体门控结果，并能把同簇漏判 conflict 一并降级。

## 数据流

1. `verify_node` 继续构造 `VerifyCase`，其中 `feature_id` 来自 test_point 到 feature 的映射。
2. `verify_cases` 继续按 feature 分批并发调用 `_verify_batch`。
3. `_verify_batch` 先拿到首轮 LLM verdict；若 `conflict_revote_enabled` 打开，则仅对首轮 verdict 为 `conflict` 的用例再执行 `revote_n-1` 次复判，并以多数票覆盖首轮 verdict。
4. `_verify_batch` 在最终 verdict 上执行既有同实体门控，并构造 `CaseVerification`。
5. `verify_cases` 聚合全部 batch 结果后，若 `verdict_reconcile_enabled` 打开，则调用 `reconcile_verdicts(results, cases)`。
6. `reconcile_verdicts` 返回新的结果映射，后续 `summarize` 读取一致化后的 verdict/bucket。

## 5a 一致化规则

- 输入：`dict[case_id, CaseVerification]` 与对应 `list[VerifyCase]`。
- 聚簇范围：只在同 `feature_id` 内聚簇。
- 相似度：对标题做规范化后，用 `difflib.SequenceMatcher` 计算相似度，默认读取 `settings.reconcile_sim`，阈值默认 0.93（离线评估发现 0.92 会误并 IAP/IAA 这类仅差产品代号的高相似标题，0.93 切散误簇且保留真同构簇）。
- 聚簇算法：组内两两比较，满足阈值则用并查集合并。
- verdict 投票：`Counter` 多数票；平票按严苛序 `conflict > undefined > ungrounded > grounded` 取更严结果。
- mismatch 协同：簇内若任一结果 `conflict_entity_mismatch=True`，则从投票候选中剔除 `conflict`，在剩余 verdict 中投票，并把 mismatch 标记传播给全簇。
- 输出：不原地破坏输入对象，返回包含更新后 `verdict`、`bucket`、`rationale`、mismatch 字段的新映射。

## 5b 复判规则

- 灰度开关：`conflict_revote_enabled` 默认 `False`。
- 复判次数：`revote_n` 默认 3，表示总投票次数；实现上首轮已存在，只追加 `revote_n-1` 次。
- 复判范围：只复判首轮 verdict 为 `conflict` 的 case；非 conflict 不追加 LLM 调用。
- 多数规则：与 5a 一致，平票取更严 verdict。
- 顺序：复判多数票先确定最终 verdict，再执行同实体门控，确保 ④ 仍是 conflict 落地前的最后一层保护。

## 配置

新增配置集中在 `src/platform_api/core/settings.py`：

- `verdict_reconcile_enabled: bool = False`
- `reconcile_sim: float = 0.92`
- `conflict_revote_enabled: bool = False`
- `revote_n: int = 3`

默认关闭保障回归。阈值和次数通过环境变量按既有 settings 机制覆盖。

## 测试策略

- 纯函数单测覆盖多数票、平票、更严序、mismatch 传播、不同 feature 不合并、标题不相似不合并。
- `verify_cases` 单测通过 mock LLM 验证开关开/关路径。
- `_verify_batch` 单测验证 conflict 子集复判、多数票覆盖、非 conflict 不复判。
- 离线脚本对现有 `.audit` 样本输出一致化簇和改判数量，供人工抽样评估误并风险。

## 回退

- 出现误聚类或改判风险时关闭 `verdict_reconcile_enabled`。
- 出现成本或复判抖动问题时关闭 `conflict_revote_enabled` 或调低 `revote_n`。
- 两个能力互相独立，可分别灰度和回滚。
