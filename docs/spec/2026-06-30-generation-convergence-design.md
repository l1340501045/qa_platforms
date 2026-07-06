# 生成侧收敛（拆条上限 + 存在性合并 + P0 配额）— 设计文档

> 状态：设计（brainstorming 产出）。承接 roadmap `2026-06-30-quality-alignment-roadmap.md` ⑥。
> 下一步：writing-plans 出实施计划（执行交 Claude Code）。
> 来源：batch `278c211f` 审查 —— 灌水（每测试点 2.81 条 / 存在性凑数 807 / P0 60%）。

## 1. 背景与问题

灌水的"生成侧"成因（③ 语义去重治"换措辞重复"，⑥ 治"结构性虚胖"，互补）：
- **拆条**：1134 测试点 → 3185 用例（**2.81×**）。根因：`write_cases` 里 LLM 把一个测试点拆成多条（TP-136-2/-3），代码还主动救回（node.py:478-491），**无每测试点条数上限**。
- **存在性凑数**：807 条（25%）"仅 1 步"的"页面有 X / 显示 Y / 默认选中 Z"，本可合并成 1 条"页面元素核对"。
- **P0 失真**：P0 占 60.4%。`risk_to_priority`（test_points/node.py:132，P0_MIN_RISK=6）是**逐条**映射，**无全局配额**。

## 2. 现状（对齐代码）

- `write_cases/node.py`：`generate_cases`（248）按 feature 分批；后处理 478-491 把 LLM 拆条（派生 ID）救回到基础 test_point，**无上限**；用例与 `test_point_id` 多对一。
- `test_points/node.py`：`risk_to_priority`（132-141，`P0_MIN_RISK=6`/`P1_MIN_RISK=3`）逐条；`GeneratedTestPoint` 有 `likelihood/impact`（42-45），但 **callbacks 落库未存 likelihood/impact**（`callbacks.py:90-99` 仅存 dimension/description/priority/derived_from/rule_id）。
- `dedup/clustering.py`：已有"占位折叠 + 边界保护 `_protected` + safe_dedup rule 护栏"，可复用其护栏思想。

## 3. 目标

三子项**互不依赖、各自灰度**，把生成侧虚胖收敛（配合 ③，总量 3185→~2000、P0<30%），**不丢覆盖**（裁剪/合并保留唯一覆盖、边界、规则锚定）。

## 4. 方案（三子项独立）

### 4.1 拆条上限（write_cases 后处理）
按 `test_point_id` 分组，每组用例数超上限 `N`（默认 3）时裁剪：**保留多样性代表**——优先保留 ①不同 `dimension` 各一 ②含边界/异常语义（复用 `_BOUNDARY_KW`）③规则锚定（rule_codes 非空）④步数更全者；其余**标 `duplicate_of` 指向该 tp 保留的代表条**（与 dedup 同机制、软标记可恢复、不硬删）。**护栏**：绝不裁掉某 test_point 的唯一用例、某规则的唯一覆盖。

### 4.2 存在性合并（write_cases 后处理）
识别"存在性用例"（步数 ≤1 且标题/预期为纯展示断言：展示/显示/包含/存在/布局/默认…）；同 `test_point_id`（且同 source_section）的多条 → 合并为 1 条"页面元素核对"用例：`preconditions` 取并、`steps` 合成"逐项核对页面元素"、`expected_results` **保留所有检查点**（不丢覆盖）。

### 4.3 P0 配额（test_points 全局）
`risk_to_priority` 逐条映射后，加**全局配额裁剪**：若 P0 占比 > `p0_quota`（默认 0.30），按 `risk=likelihood×impact` 降序保留 top 配额数为 P0，其余 P0 降 P1（同 risk 同等处理，稳定排序）。**结构化覆盖点豁免（自审）**：`expander`（权限矩阵/状态机，node.py 硬 P0、无 likelihood/impact）/`rule_anchor`/`mandatory_dimensions` 等重要覆盖点 **赋最高 risk 或排除出配额裁剪**——避免配额误降关键结构化覆盖；配额**只裁 risk 派生的边际 P0**。**顺带**：callbacks 落 test_points 时存 `likelihood/impact`（未来可离线复算 + 用例 priority 可追溯）。

## 5. 设计决策与权衡（自审）

- **后处理 vs 生成期**：4.1/4.2 做**后处理**（对现有 3185 条离线可验、**不烧 PRD**）；"prompt 约束少生成"作 future（要重新生成才验，烧 PRD）。
- **不丢覆盖护栏**：裁剪/合并复用 dedup 的护栏思想——保唯一覆盖、保边界（`_protected`）、保规则锚定（safe_dedup）；存在性合并保留全部检查点。
- **P0 配额需 risk 值**：现有 test_points 落库未存 likelihood/impact → 配额只能在 test_points 阶段（内存有 risk）做；本步**顺带补落 likelihood/impact**，并以单测验配额逻辑，真实分布留终验（或重新生成）。
- **三子项独立灰度**：`split_cap_enabled` / `existence_merge_enabled` / `p0_quota_enabled`，可分别开关、分别交付。
- **⑥ 与 ③ 互补、有先后**：⑥ 在 `write_cases`（生成后、verify 前）治"同测试点拆条 + 存在性凑数"，③ 在 `dedup`（verify 后）治"跨测试点换措辞重复"；**先 ⑥ 后 ③**，互不重复。存在性合并后的"多检查点"用例，verify 按 rubric"每条关键断言分别核对"仍可逐点判（合并不增核验难度）。

## 6. 范围

**做**：4.1 拆条上限后处理 + 4.2 存在性合并后处理 + 4.3 P0 配额（+ 落 likelihood/impact）+ 三开关 + 单测 + 离线评估（4.1/4.2）。

**不做（YAGNI）**：不做 prompt 生成期约束（future）；不改 ③ 语义去重 / verify / provenance；不硬删（裁剪同样软标记 `duplicate_of` 或 `review_status`，可恢复）；不改 risk 公式本身（只加配额）。

## 7. 验收

- **4.1/4.2 离线**：用现有 `.audit/278c211f/.../cases.jsonl` 跑后处理，每测试点 ≤N、存在性合并后总量明显下降；抽查未丢覆盖（边界/异常/规则锚定仍在）。
- **4.3**：单测——造 likelihood/impact 分布，配额裁剪后 P0≤30% 且保留的是 risk 最高者；callbacks 落库含 likelihood/impact。
- **零回归**：三开关关 → 逐字节现状。
- 全量回归绿；ruff 干净；提交隔离。

## 8. 风险

- **裁剪/合并丢覆盖** → 护栏（唯一覆盖/边界/规则锚定/全检查点保留）+ 离线抽查 + 软标记可恢复。
- **P0 配额误降高价值** → 严格按 risk 降序；同 risk 稳定序；阈值可配。
- **存在性误识别**（把含判定的用例当存在性合并）→ 仅合并"步数≤1 且纯展示断言"，保守。
