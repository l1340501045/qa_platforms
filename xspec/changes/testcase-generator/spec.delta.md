# testcase-generator 增量需求变更

> 基线：xspec/modules/testcase-generator/spec.md v0.1

## 0. 文档信息

| 属性 | 内容 |
| :--- | :--- |
| **所属变更** | CHG-20260609-001 |
| **基线版本** | testcase-generator/spec.md v0.1 |
| **变更类型** | modified |
| **创建时间** | 2026-06-09 |

---

## 1. 变更概述

**变更动机**：当前 iteration_service 在迭代时断裂用例血缘（软删除旧用例 + 插入全新 UUID，仅靠 test_point_id 隐式关联），且跨批次/跨需求重生成时 test_points 是按批次新建的，没有任何锚点。需要改造以支撑单条用例级版本化追溯。

**交付分段**：
- **第一段**：**不动本模块**（禁止改 src/testcase_generator/ 生成流水线代码）
- **第二段**：改造 iteration_service + 生成写入逻辑，建立逻辑用例 ID + 版本记录，对齐 quality_flywheel

---

## 2. 第一段约束

本模块在第一段交付中**不做任何改动**。原因：
- 第一段目标是"让用例可被发现和查看"，是纯前端+API层工程
- 版本化和锚点需要深入研究现有数据模型和生成逻辑，属研究性工程
- 避免在稳定性尚未验证的阶段引入生成流水线风险

---

## 3. 第二段变更内容

### 3.1 iteration_service 改造

**当前问题**（事实 5）：
- 被改用例软删除（review_status=deleted）+ 插入全新 UUID 用例
- 仅靠 test_point_id 隐式关联前后版本
- 没有显式 parent 指针、没有持久化修改原因
- 跨批次重生成时 test_points 按批次新建，无任何跨批次锚点

**改造目标**：
- 迭代时不再"删旧建新"，而是在同一逻辑用例下追加新版本
- 显式记录 parent_version_id、change_reason、change_type
- 对齐写入 quality_flywheel 表

**改造后行为**：

| 操作 | 改造前 | 改造后 |
| :--- | :--- | :--- |
| 批次内迭代（需修改→重生成） | 旧用例 deleted + 新 UUID 插入 | 旧用例保留，新版本关联同一 logical_case_id，change_type=iteration |
| 跨批次重生成（同文档新触发） | 全新批次，全新用例，无关联 | 通过锚点匹配已有 logical_case，创建新版本，change_type=ai_regen |
| 需求变更重生成（新文档触发） | 全新批次，无关联 | 通过锚点匹配，创建新版本，change_type=requirement_change |

### 3.2 生成写入逻辑增强

**write-cases stage 变更**：
- 每条用例生成完成后，计算 anchor_key
- 查询 logical_case 表是否有匹配记录
- 匹配到 → 创建 case_version 记录（version_no 递增）
- 未匹配 → 创建新 logical_case + 第一条 case_version
- AI 语义匹配的结果标记 needs_human_confirm=true

**与 quality_flywheel 双写**：
- 每次创建 case_version 时同步写入 quality_flywheel
- case_version.change_reason → quality_flywheel.modification_reason
- case_version.change_type → quality_flywheel.modification_type
- 若用例被标记为 is_few_shot_candidate，在 quality_flywheel 中同步标记

### 3.3 锚点计算逻辑

**确定性锚点键生成规则**：
```
anchor_key = hash(system_id + source_section + primary_dimension + test_point_description_fingerprint)
```

- system_id：用例所属系统 UUID
- source_section：provenance.source_section（功能模块名）
- primary_dimension：dimensions 数组排序后取第一个元素（保证确定性，不依赖数组顺序）
- test_point_description_fingerprint：该用例关联的 test_point.description 去除空白和标点后的 MD5 前 16 位
  - 理由：test_point.description 描述"测试点意图"，跨批次稳定性远高于 title（title 是 AI 每次可变表述）
  - title 相似度仅留给 AI 兜底层使用

**锚点匹配优先级**：
1. anchor_key 完全匹配 → 确定性关联
2. anchor_key 不匹配但 source_section 相同 → 触发 AI 语义比对
3. AI 语义比对（比较 title + steps 文本相似度）：
   - 置信度 ≥ 0.85 → 关联但标记待人工确认
   - 置信度 < 0.85 → 视为全新逻辑用例

---

## 4. 新增用户故事

| 编号 | 角色 | 行为 | 目的 | 优先级 |
| :--- | :--- | :--- | :--- | :--- |
| US-TG-01 | 作为 QA 工程师 | 我想要迭代后的用例保留与原版本的关联 | 以便追溯一条用例的演化过程和修改原因 | P0 |
| US-TG-02 | 作为 QA 工程师 | 我想要跨批次重生成时自动识别"同一条用例" | 以便不会丢失该用例的历史 review 和修改记录 | P0 |
| US-TG-03 | 作为 QA 工程师 | 我想要 AI 匹配的用例关联标记为"待确认" | 以便我决定是否接受 AI 的判断 | P1 |

---

## 5. 变更验收标准

| 编号 | 关联 | Given（前置状态） | When（触发动作） | Then（预期结果） | 优先级 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| AC-TG-01 | US-TG-01 | 批次中用例 A 被标记"需修改"并触发迭代 | 迭代完成 | 新版本与旧版本关联同一 logical_case_id，case_version 表有 2 条记录，change_type=iteration | P0 |
| AC-TG-02 | US-TG-02 | 文档 X 之前生成过批次（含用例"登录验证"，其 test_point.description 为"验证用户名密码登录"） | 对文档 X 再次触发生成 | 新批次中对应用例通过 test_point_description_fingerprint 锚点匹配到已有 logical_case，创建 v2 | P0 |
| AC-TG-03 | US-TG-03 | 新批次用例锚点键不匹配但 AI 语义相似度=0.9 | 生成完成 | case_version 创建成功，logical_case.needs_human_confirm=true，anchor_method=ai_semantic | P1 |
| AC-TG-04 | US-TG-01 | 迭代生成新版本用例 | 检查 quality_flywheel 表 | 存在对应记录，modification_reason 与 case_version.change_reason 一致 | P0 |
| AC-TG-05 | 3.3 | 新批次用例 AI 语义匹配置信度=0.6 | 锚点匹配流程 | 创建新 logical_case（不关联已有），anchor_method=deterministic（新建） | P1 |

---

## 6. 约束与依赖

- 第二段启动前提：第一段前端+API层已就绪且验证通过
- logical_case 和 case_version 表设计由 platform-api 模块负责建表迁移
- 本模块负责在生成/迭代写入时调用 platform-api 提供的版本记录服务
- 必须对齐 quality_flywheel 表，禁止另起竞争的版本追踪表
- AI 语义匹配逻辑可复用现有 LLM 调用基础设施（与 comprehend/review 阶段同链路）
