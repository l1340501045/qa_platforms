# platform-api 增量需求变更

> 基线：xspec/modules/platform-api/spec.md v1.0

## 0. 文档信息

| 属性 | 内容 |
| :--- | :--- |
| **所属变更** | CHG-20260609-001 |
| **基线版本** | platform-api/spec.md v1.0 |
| **变更类型** | modified |
| **创建时间** | 2026-06-09 |

---

## 1. 变更概述

**变更动机**：当前后端缺少系统级/文档级批次列表 API（仅有单批次详情），无通知消息能力，无搜索接口，导出创建需手填 UUID。需新增一组 API 支撑前端信息架构重构和用例可视化。

**交付分段**：
- **第一段**：批次列表 API、用例树形聚合 API、通知消息 API、搜索 API、导出选项 API、trust_level 语义修正、stage_artifacts 透传、失败重试 API
- **第二段**：逻辑用例 ID + 版本记录 API、锚点匹配 API

---

## 2. 新增用户故事

| 编号 | 角色 | 行为 | 目的 | 优先级 |
| :--- | :--- | :--- | :--- | :--- |
| US-API-01 | 作为前端 | 我需要获取某个系统下的所有批次列表 | 以便在系统详情"批次历史" Tab 中展示 | P0 |
| US-API-02 | 作为前端 | 我需要获取某个系统的用例树形聚合数据 | 以便渲染 PRD → 功能模块 → 用例 的树 | P0 |
| US-API-03 | 作为前端 | 我需要获取/管理通知消息 | 以便铃铛展示未读数和消息列表 | P0 |
| US-API-04 | 作为前端 | 我需要跨系统搜索用例 | 以便全局用例中心的搜索功能 | P1 |
| US-API-05 | 作为前端 | 我需要从失败的阶段重试批次 | 以便不必重新触发完整生成 | P1 |
| US-API-06 | 作为前端 | 我需要获取批次/系统的下拉选项列表 | 以便导出创建时提供选择器 | P0 |
| US-API-07 | 作为前端 | 我需要获取某条用例的完整版本历史 | 以便详情面板展示演化过程 | P1 |

---

## 3. 新增接口概要

### 3.1 批次列表（第一段）

| 接口 | 方法 | 路径 | 说明 |
| :--- | :--- | :--- | :--- |
| 系统批次列表 | GET | /api/v1/systems/:id/batches | 分页返回该系统下所有批次，含状态/文档名/时间 |
| 文档批次列表 | GET | /api/v1/documents/:id/batches | 分页返回该文档的所有生成批次 |

**请求参数**：page, per_page, status（可选筛选）

**响应结构**：
```
{
  items: [{ id, document_id, document_title, status, total_cases, started_at, completed_at, created_at }],
  total, page, per_page, total_pages
}
```

### 3.2 用例树形聚合（第一段）

| 接口 | 方法 | 路径 | 说明 |
| :--- | :--- | :--- | :--- |
| 系统用例树 | GET | /api/v1/systems/:id/case-tree | 返回按 PRD → 功能模块 → 用例 聚合的树形数据 |

**请求参数**：batch_id（可选，默认取各文档最新批次）、priority（可选）、review_status（可选）

**响应结构**：
```
{
  tree: [{
    document_id, document_title,
    modules: [{
      module_name,   // 来自 provenance.source_section
      case_count,
      cases: [{ id, title, priority, trust_level, review_status }]
    }]
  }]
}
```

**聚合逻辑**：
- 默认展示各文档最新已完成批次的用例（status=completed 或 archived）
- 功能模块名称从用例的 provenance.source_section 字段派生
- 排除 review_status=deleted 的用例（除非筛选条件明确要求）

**树根归属规则（已定稿）**：
- 树根 = 种子文档（即触发生成批次的 document，batch.document_id 指向的文档）
- 由技术方案文档（tech_doc）派生的用例处理：当用例的 provenance.source_section 指向技术文档内容时，该用例仍归属到其所在批次的种子文档根节点下，按 source_section 归入对应功能模块
- 理由：批次由种子文档触发，技术文档仅作为辅助上下文输入，不单独成为树根

### 3.3 通知消息（第一段）

| 接口 | 方法 | 路径 | 说明 |
| :--- | :--- | :--- | :--- |
| 未读数 | GET | /api/v1/notifications/unread-count | 返回未读消息数量 |
| 消息列表 | GET | /api/v1/notifications | 分页返回消息列表 |
| 标记已读 | PATCH | /api/v1/notifications/:id/read | 标记单条已读 |
| 全部已读 | POST | /api/v1/notifications/mark-all-read | 全部标记已读 |

**数据模型（新增表 notification）**：

| 字段 | 类型 | 说明 |
| :--- | :--- | :--- |
| id | UUID | 主键 |
| type | VARCHAR(50) | 消息类型：batch_completed / batch_failed / batch_suspended |
| title | TEXT | 消息标题 |
| body | TEXT | 消息正文（可选） |
| target_type | VARCHAR(50) | 跳转目标类型：batch |
| target_id | UUID | 跳转目标 ID |
| is_read | BOOLEAN | 是否已读 |
| actor | VARCHAR(100) | 操作者（默认 "system"，预留多人协作） |
| created_at | TIMESTAMP | 创建时间 |

**消息生成时机**：在 `api/v1/callbacks.py` 的三个回调处理逻辑中创建通知记录：
- `pipeline-complete` 回调（批次 → PENDING_REVIEW）→ 创建 type=batch_completed 通知
- `pipeline-failed` 回调（批次 → FAILED）→ 创建 type=batch_failed 通知
- `pipeline-suspended` 回调（批次 → SUSPENDED）→ 创建 type=batch_suspended 通知

### 3.4 全局搜索（第一段）

| 接口 | 方法 | 路径 | 说明 |
| :--- | :--- | :--- | :--- |
| 用例搜索 | GET | /api/v1/cases/search | 跨系统搜索用例 |

**请求参数**：q（关键词）、system_id（可选）、priority（可选）、review_status（可选）、page、per_page

**搜索实现**：
- 搜索范围：用例 title + steps[].action 文本
- 中文搜索方案：pg_trgm 扩展提供模糊匹配，ILIKE 兜底精确匹配
- 索引要求：steps 为 JSONB 列，需建表达式索引或生成列以支持 pg_trgm（例如生成列 steps_text 提取所有 action 拼接为 TEXT）
- 排序：相关度优先（pg_trgm similarity 分数）
- 后续升级路径：引入 pg_jieba 分词或独立搜索服务

### 3.5 失败重试（第一段）

| 接口 | 方法 | 路径 | 说明 |
| :--- | :--- | :--- | :--- |
| 从失败步重试 | POST | /api/v1/batches/:id/retry | 从失败的 stage 恢复执行 |

**前置条件**：批次 status 为 failed

**行为（主路径：复用 LangGraph checkpoint resume）**：
- 流水线使用 AsyncPostgresSaver 持久化图状态，已有 _resume_pipeline 恢复机制
- 调用时从最近一次持久化的 checkpoint 恢复，自动从失败节点重新执行
- 批次 status 恢复为 running
- stage_artifacts 中失败 stage 状态更新为 running

**降级路径（checkpoint 不可用时）**：
- 若 checkpoint 数据损坏或不存在，降级为整批重跑（重新触发完整流水线）
- 降级时在响应中标注 `"fallback": true`，通知前端展示"已整批重跑"提示
- 原有 stage_artifacts 全部重置为 pending

### 3.6 导出选项（第一段）

| 接口 | 方法 | 路径 | 说明 |
| :--- | :--- | :--- | :--- |
| 批次选项列表 | GET | /api/v1/batches/options | 返回可导出的批次摘要列表（用于下拉选择） |
| 系统选项列表 | GET | /api/v1/systems/options | 返回系统摘要列表（用于下拉选择） |

**批次选项响应**：
```
[{ id, document_title, status, created_at, system_name }]
```
仅返回 status 为 completed 或 archived 的批次。

### 3.7 trust_level 语义修正（第一段）

**当前问题**：trust_level 后端为整数 1–5，前端误按 0–1 浮点数 ×100 展示，导致恒显示 100%。

**正确定义（信源信任度，数字越小越可信）**：

| trust_level | 语义 | confidence_note | 前端展示 |
| :--- | :--- | :--- | :--- |
| 1 | 高可信 | （无） | 绿色标签"高可信" |
| 2 | 高可信 | （无） | 绿色标签"高可信" |
| 3 | 中可信 | （无） | 黄色标签"中可信" |
| 4 | 中可信 | "来源为 UI 设计稿，建议人工确认交互细节" | 黄色标签"中可信" + note 提示 |
| 5 | 低可信 | "来源含原型探索，原型可能有交互 bug" | 红色标签"低可信" + note 提示 |

**修正规则**：
- API 响应继续返回整数 1–5，禁止转为百分比
- 前端按上表映射为档位标签 + confidence_note 文字展示
- 详情面板展示格式：「信源等级：{档位标签}」+ note（若有）

### 3.8 逻辑用例 ID + 版本记录（第二段）

| 接口 | 方法 | 路径 | 说明 |
| :--- | :--- | :--- | :--- |
| 用例版本历史 | GET | /api/v1/cases/:logical_case_id/versions | 获取逻辑用例的全部版本 |
| 版本详情 | GET | /api/v1/cases/:logical_case_id/versions/:version_no | 获取某版本快照 |
| 版本对比 | GET | /api/v1/cases/:logical_case_id/diff?v1=N&v2=M | 两版本差异对比 |

**数据模型变更（第二段，专题 A 详细设计）**：

新增表 `logical_case`：

| 字段 | 类型 | 说明 |
| :--- | :--- | :--- |
| id | UUID | 逻辑用例 ID（稳定锚点） |
| system_id | UUID | 所属系统 |
| anchor_key | VARCHAR(512) | 确定性锚点键（system + source_section + dimension + test_point_description 指纹） |
| anchor_method | VARCHAR(20) | 锚定方式：deterministic / ai_semantic |
| ai_confidence | FLOAT | AI 匹配置信度（仅 ai_semantic 时有值） |
| needs_human_confirm | BOOLEAN | 是否待人工确认（AI 匹配时为 true） |
| created_at | TIMESTAMP | 创建时间 |

新增表 `case_version`（对齐复用 quality_flywheel，不另起竞争表）：

| 字段 | 类型 | 说明 |
| :--- | :--- | :--- |
| id | UUID | 版本记录主键 |
| logical_case_id | UUID | FK → logical_case.id |
| version_no | INTEGER | 版本号（递增） |
| test_case_id | UUID | FK → test_case.id（指向具体用例快照） |
| parent_version_id | UUID | FK → case_version.id（上一版本，可为空） |
| change_reason | TEXT | 变更原因 |
| change_type | VARCHAR(30) | ai_regen / human_edit / requirement_change / iteration |
| actor | VARCHAR(100) | 操作者（ai / 具体用户名） |
| batch_id | UUID | 产生该版本的批次 |
| created_at | TIMESTAMP | 创建时间 |

**与 quality_flywheel 对齐规则**：
- case_version.change_reason 对应 quality_flywheel.modification_reason
- case_version.change_type 对应 quality_flywheel.modification_type
- 当用例生成时写入 case_version 的同时写入 quality_flywheel（双写保持一致）
- 禁止新建独立的版本追踪表与 quality_flywheel 竞争

**用例身份锚点混合方案（专题 A）**：

1. **确定性锚点逻辑键**：`system_id + source_section（功能模块）+ primary_dimension + test_point_description_fingerprint`
   - test_point_description_fingerprint：该用例关联的 test_point.description 去除空白标点后的 MD5 前 16 位
   - 理由：test_point.description 描述"测试点意图"，比用例 title 跨批次稳定得多（title 是 AI 每次可变的表述）
   - primary_dimension：dimensions 数组排序后取第一个元素（保证确定性，不依赖数组顺序）
   - 当新批次用例的锚点键与已有 logical_case 完全匹配时，创建新版本

2. **跨批次匹配流程**：
   - 新批次完成后，逐条用例计算 anchor_key
   - 精确匹配已有 logical_case → 创建新 case_version
   - 无精确匹配 → 触发 AI 语义匹配（比对 title + steps 相似度）
   - AI 匹配置信度 ≥ 0.85 → 创建版本但标记 needs_human_confirm=true
   - AI 匹配置信度 < 0.85 → 视为全新逻辑用例，创建新 logical_case

3. **待人工确认交互**：
   - 前端在用例详情面板标注"AI 匹配待确认"
   - 用户可确认（接受匹配）或拒绝（拆分为新逻辑用例）

---

## 4. 专题 B：流水线可观测性数据透传

**变更内容**（第一段）：
- 现有 GET /api/v1/batches/:id 响应中 stage_progress.stages 已含 name/status
- 需增加透传 stage_artifacts 表的 duration_ms、started_at、completed_at、open_questions 字段
- 失败 stage 需透传 error_message（从 stage_artifacts 或批次异常记录中提取）

**响应结构增强**：
```
stage_progress.stages: [{
  name, status,
  duration_ms,      // 新增
  started_at,       // 新增
  completed_at,     // 新增
  error_message     // 新增（仅 failed 时有值）
}]
```

---

## 5. 专题 C：跨版本 Review 状态继承规则

**设计决策**（第二段）：

| 场景 | 规则 | 理由 |
| :--- | :--- | :--- |
| v1 已确认，需求变更生成 v2 | v2 回到"待审" | 需求变更可能导致用例失效，必须重新审阅 |
| v1 已确认，同需求迭代生成 v2（仅修改表述） | v2 保持"已确认" | 微调表述不影响测试意图 |
| v1 需修改，迭代生成 v2 | v2 回到"待审" | 修改后需重新审阅 |
| v1 已删除，新批次匹配到同一逻辑用例 | 新版本为"待审" | 被删除的用例重新出现需确认 |

**判定 change_type 与继承关系**：
- change_type = requirement_change → 一律回到"待审"
- change_type = iteration（批次内迭代）→ 回到"待审"
- change_type = human_edit（人工微调）→ 保持原状态
- change_type = ai_regen（同需求纯表述优化）→ 保持原状态

---

## 6. 变更验收标准

| 编号 | 关联 | Given（前置状态） | When（触发动作） | Then（预期结果） | 优先级 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| AC-API-01 | US-API-01 | 系统下有 3 个批次 | GET /systems/:id/batches | 返回 3 条批次记录，含文档标题/状态/时间 | P0 |
| AC-API-02 | US-API-02 | 系统有 2 篇 PRD 各生成 1 个完成批次 | GET /systems/:id/case-tree | 返回树形数据，2 个文档根节点各含功能模块和用例 | P0 |
| AC-API-03 | US-API-03 | 有 2 条未读通知 | GET /notifications/unread-count | 返回 {"count": 2} | P0 |
| AC-API-04 | US-API-03 | 有 1 条未读通知 | PATCH /notifications/:id/read | 该通知 is_read 变为 true，未读数变为 0 | P0 |
| AC-API-05 | US-API-04 | 存在标题含"登录"的用例 5 条 | GET /cases/search?q=登录 | 返回 5 条匹配用例 | P1 |
| AC-API-06 | US-API-05 | 批次在"理解"阶段失败 | POST /batches/:id/retry | 批次状态恢复 running，从"理解"阶段重新开始 | P1 |
| AC-API-07 | US-API-06 | 有 3 个已完成批次 | GET /batches/options | 返回 3 条批次摘要（id/文档名/状态/时间） | P0 |
| AC-API-08 | 3.3 | 批次生成完成 | 检查 notification 表 | 新增 1 条 type=batch_completed 的通知记录 | P0 |
| AC-API-09 | §4 | 存在 stage_artifacts 数据 | GET /batches/:id | stages 含 duration_ms/started_at/completed_at/error_message | P0 |
| AC-API-10 | US-API-07 | 逻辑用例有 3 个版本 | GET /cases/:id/versions | 返回 3 条版本记录，含 change_reason/change_type/actor | P1 |

---

## 7. 约束与依赖

- 通知生成与批次状态机联动：在 api/v1/callbacks.py 的 pipeline-complete/failed/suspended 回调中触发通知创建
- 搜索依赖 PostgreSQL pg_trgm 扩展（需确认已安装或添加 migration）；steps(JSONB) 需生成列或表达式索引
- 第二段逻辑用例 ID 和版本表设计需与 testcase-generator 的 iteration_service 改造协同
- case_version 表与 quality_flywheel 表双写，禁止数据不一致
- 所有新表预留 actor/author 字段支撑后续多人协作
