# testcase-generator 增量任务清单 — CHG-20260609-001

> 基线：xspec/modules/testcase-generator/task.md (CHG-20260605-001)

## 文档信息

| 属性 | 内容 |
| :--- | :--- |
| **所属变更** | CHG-20260609-001 |
| **模块名称** | testcase-generator |
| **模块类型** | ai-agent (modified) |
| **交付分段** | 第二段（第一段不动本模块） |
| **创建时间** | 2026-06-10 |

---

## 任务格式

```
- [ ] T{NNN} [P?] {优先级} 任务描述（含具体文件路径）
  depends: T{NNN}, T{NNN}@{other-module}
```

| 标记 | 含义 |
| :--- | :--- |
| `T{NNN}` | 模块内唯一编号，从 T001 起编 |
| `[P]` | 可并行：操作不同文件、无依赖未完成任务 |
| 优先级 | P0（必须）/ P1（重要）/ P2（可选） |
| `depends:` | 依赖标注（缩进换行）。模块内：`T010`；跨模块：`T020@platform-api`。无依赖则不写此行 |

---

## 前置条件

- 第一段 platform-api 和 platform-web 交付验证通过
- `logical_cases` 和 `case_versions` 表已由 platform-api 建立并迁移完成
- quality_flywheel 表字段扩展已完成（modification_type / modification_reason）

---

## 阶段 1：环境与基础

**目标**：anchor_calculator 纯函数模块就绪、AnchorConfig 配置加载完成、依赖声明更新

- [ ] T001 [P] P0 新增 AnchorConfig 配置文件，定义 hash_algorithm / similarity_threshold / max_candidates / cache_ttl / batch_size / flywheel_dual_write 等参数 `src/testcase_generator/config/anchor_config.py`
- [ ] T002 [P] P0 新增 anchor_calculator 纯函数模块骨架（normalize_text + compute_anchor_key 函数签名）`src/testcase_generator/utils/anchor_calculator.py`
- [ ] T003 [P] P0 更新 pyproject.toml 新增依赖（numpy，用于余弦相似度计算）`pyproject.toml`
- [ ] T004 P0 验证 platform-api logical_cases / case_versions 表可通过共享 models 包 import `src/testcase_generator/db.py`
  depends: T003, T025@platform-api

**检查点**：`from testcase_generator.utils.anchor_calculator import compute_anchor_key` 成功；AnchorConfig 加载无报错；`from platform_api.models.testcase import LogicalCase, CaseVersion` 成功

---

## 阶段 2：数据层

**目标**：PipelineState 扩展、新增 Pydantic Schema、Repository 层适配

- [ ] T005 P0 PipelineState 扩展：新增 `anchor_results: list[AnchorResult]` 和 `version_records: list[VersionRecord]` 字段 `src/testcase_generator/schemas/pipeline_state.py`
  depends: T006, T007
- [ ] T006 [P] P0 新增 Pydantic Schema：AnchorResult（case_id, anchor_key, match_type, logical_case_id, confidence, needs_human_confirm）`src/testcase_generator/schemas/anchor.py`
- [ ] T007 [P] P0 新增 Pydantic Schema：VersionRecord（logical_case_id, version_no, test_case_id, change_type, change_reason, parent_version_id）`src/testcase_generator/schemas/anchor.py`
- [ ] T008 [P] P0 新增 Pydantic Schema：MatchInput / LogicalCaseCandidate / MatchResult（语义匹配输入输出）`src/testcase_generator/schemas/anchor.py`
- [ ] T009 P0 Repository 层扩展：新增 LogicalCaseRepository（查询 by anchor_key / by system_id+source_section）`src/testcase_generator/repositories/logical_case_repo.py`
  depends: T004
- [ ] T010 P0 Repository 层扩展：新增 CaseVersionRepository（查询 latest version / 写入新版本）`src/testcase_generator/repositories/case_version_repo.py`
  depends: T004

**检查点**：PipelineState 类型检查通过；AnchorResult / VersionRecord / MatchResult 可实例化；Repository 可正常 SELECT/INSERT

---

## 阶段 3：功能实现

**目标**：锚点计算、语义匹配、版本写入、后置处理集成、iteration_service 改造全部完成

### US-TG-02: anchor_calculator 实现（AC-TG-02 / AC-TG-05）

- [ ] T011 P0 实现 normalize_text：Unicode NFKC 归一化 + 转小写 + 去空白 + 去标点 `src/testcase_generator/utils/anchor_calculator.py`
  depends: T002
- [ ] T012 P0 实现 compute_anchor_key：拼接 system_id|source_section|dimension|tp_desc 后 MD5，返回 32 字符 hex string `src/testcase_generator/utils/anchor_calculator.py`
  depends: T011
- [ ] T013 P0 实现 compute_batch：批量计算 anchor_key（遍历 test_cases，system_id 经 batch.system_id 取得，dimension 取 sorted(dimensions)[0]）`src/testcase_generator/utils/anchor_calculator.py`
  depends: T012, T001

### US-TG-02: semantic_matcher 实现（AC-TG-03 / AC-TG-05）

- [ ] T014 P0 新建 SemanticMatcher 类骨架：__init__ 接收 EmbeddingClient + similarity_threshold + redis_client `src/testcase_generator/services/semantic_matcher.py`
  depends: T001, T008
- [ ] T015 P0 实现 _build_case_text：拼接 title + steps 为 embedding 输入文本 `src/testcase_generator/services/semantic_matcher.py`
  depends: T014
- [ ] T016 P0 实现 _batch_encode：批量 embedding 编码（调用 EmbeddingClient.embed_batch 返回 list[list[float]]），含 Redis 缓存逻辑（key=embedding:{md5(text)}, TTL=86400s）`src/testcase_generator/services/semantic_matcher.py`
  depends: T015
- [ ] T017 P0 实现 cosine_similarity 纯函数：numpy 向量余弦相似度计算 `src/testcase_generator/services/semantic_matcher.py`
  depends: T003
- [ ] T018 P0 实现 match 方法：批量编码 → 余弦相似度 → 阈值判定（>=0.85 匹配+needs_human_confirm / <0.85 不匹配创建新 logical_case）`src/testcase_generator/services/semantic_matcher.py`
  depends: T016, T017
- [ ] T019 P1 实现 match_with_fallback：Embedding 服务不可用时降级为创建新 logical_case `src/testcase_generator/services/semantic_matcher.py`
  depends: T018

### US-TG-01: version_writer 实现（AC-TG-01 / AC-TG-04）

- [ ] T020 P0 新建 VersionWriter 类骨架：__init__ 接收 AsyncSession `src/testcase_generator/services/version_writer.py`
  depends: T009, T010
- [ ] T021 P0 实现 write_version 单条写入：单事务三写（logical_case + case_version + quality_flywheel），system_id 经 batch.system_id 取得 `src/testcase_generator/services/version_writer.py`
  depends: T020, T006, T007
- [ ] T022 P0 实现 _inherit_review_status：review 状态继承规则（iteration/requirement_change → pending；human_edit/ai_regen → 保持原状态）`src/testcase_generator/services/version_writer.py`
  depends: T021
- [ ] T023 P0 实现 process_batch：批量处理逻辑（精确匹配 → embedding 兜底 → 新建），编排 anchor_calculator + semantic_matcher `src/testcase_generator/services/version_writer.py`
  depends: T021, T022, T018

### US-TG-01: write-cases 后置处理节点集成（AC-TG-02）

- [ ] T024 P0 新建 write_cases_with_anchor_node 包装函数：在原有 write_cases 节点后追加锚点计算+版本写入后置处理 `src/testcase_generator/stages/write_cases/post_anchor.py`
  depends: T013, T023
- [ ] T025 P0 修改 StateGraph 注册：将 write_cases 节点替换为 write_cases_with_anchor_node `src/testcase_generator/pipeline/graph.py`
  depends: T024

### US-TG-01: iteration_service 改造（AC-TG-01 / AC-TG-04）

- [ ] T026 P0 改造 iterate 方法：不再软删除旧用例（移除 review_status='deleted' 逻辑），保留旧版本 `src/testcase_generator/services/iteration_service.py`
  depends: T020
- [ ] T027 P0 改造 iterate 方法：新版本用例通过 version_writer.write_version 写入（change_type='iteration', parent_version_id 指向上一版本）`src/testcase_generator/services/iteration_service.py`
  depends: T026, T021
- [ ] T028 P0 改造 iterate 方法：确保 quality_flywheel 双写一致（modification_reason 与 case_version.change_reason 对齐）`src/testcase_generator/services/iteration_service.py`
  depends: T027

**检查点**：anchor_calculator 对同输入产出相同 anchor_key；semantic_matcher 能返回置信度并按阈值判定；version_writer 三写事务原子性验证通过；iteration_service 迭代后不再断裂血缘

---

## 阶段 4：集成与收尾

**目标**：单元测试、集成测试、评测数据集、离线评估、阈值校准、跨模块联调

### 单元测试

- [ ] T029 [P] P0 anchor_calculator 纯函数单元测试：确定性验证（同输入同输出）、归一化验证（空白/标点/大小写不影响）、边界输入（空字符串/特殊字符/超长文本）`tests/testcase_generator/unit/test_anchor_calculator.py`
  depends: T012
- [ ] T030 [P] P0 semantic_matcher 单元测试：cosine_similarity 计算正确性、阈值判定边界（0.84/0.85/0.86）、降级逻辑 `tests/testcase_generator/unit/test_semantic_matcher.py`
  depends: T018, T019
- [ ] T031 [P] P0 version_writer 单元测试：review 状态继承规则全路径覆盖、change_type 枚举完整性 `tests/testcase_generator/unit/test_version_writer.py`
  depends: T022

### 集成测试

- [ ] T032 P0 write-cases 后置处理端到端集成测试：模拟完整流水线 → 验证 logical_case + case_version + quality_flywheel 三表写入正确 `tests/testcase_generator/integration/test_post_anchor_e2e.py`
  depends: T025, T028
- [ ] T033 P0 iteration_service 血缘集成测试：迭代后 parent_version_id 正确指向、同一 logical_case_id 下多版本 `tests/testcase_generator/integration/test_iteration_versioning.py`
  depends: T028
- [ ] T034 P0 跨批次锚点匹配集成测试：同文档二次生成时通过 anchor_key 匹配已有 logical_case `tests/testcase_generator/integration/test_cross_batch_anchor.py`
  depends: T025
- [ ] T035 P1 embedding 匹配集成测试：无精确匹配时触发 embedding 比对，验证 needs_human_confirm=true `tests/testcase_generator/integration/test_embedding_match.py`
  depends: T025

### 评测与校准

- [ ] T036 P0 评测数据集构造：Golden-set 50 条（覆盖精确匹配/embedding 匹配/不匹配三种场景，标注预期 match_type 和 logical_case_id）`tests/testcase_generator/evaluation/golden_set_anchor.yaml`
  depends: T025
- [ ] T037 P0 离线评估运行：基于 golden-set 运行 anchor_calculator + semantic_matcher 全流程，输出 precision/recall/F1 `tests/testcase_generator/evaluation/run_evaluation.py`
  depends: T036
- [ ] T038 P1 阈值校准：基于评估结果调整 similarity_threshold（目标 precision >= 0.9），更新 AnchorConfig `src/testcase_generator/config/anchor_config.py`
  depends: T037

### 跨模块联调

- [ ] T039 P0 与 platform-api 版本 API 联调：验证 GET /cases/:id/versions 返回 version_writer 写入的 case_version 记录 `tests/testcase_generator/integration/test_api_version_sync.py`
  depends: T032, T030@platform-api
- [ ] T040 P0 与 platform-api quality_flywheel API 联调：验证双写后 flywheel 记录字段完整（modification_reason / modification_type 对齐）`tests/testcase_generator/integration/test_api_flywheel_sync.py`
  depends: T032, T030@platform-api

**检查点**：单元测试全部通过；集成测试端到端验证三表写入正确；golden-set 评估 precision >= 0.9；与 platform-api 版本 API 联调返回正确版本链

---

## 验收标准追溯矩阵

| AC 编号 | 验收标准 | 覆盖任务 | 验证方式 |
| :--- | :--- | :--- | :--- |
| AC-TG-01 | 迭代后版本关联 logical_case | T026, T027, T028, T033 | 集成测试：迭代后同一 logical_case_id 下存在多版本记录 |
| AC-TG-02 | 跨批次锚点匹配 | T012, T013, T024, T025, T034 | 集成测试：同文档二次生成匹配已有 logical_case 创建 v2 |
| AC-TG-03 | AI embedding 匹配待确认 | T018, T019, T023, T035 | 集成测试：embedding 匹配时 needs_human_confirm=true |
| AC-TG-04 | quality_flywheel 双写一致 | T021, T028, T032, T040 | 集成测试：case_version.change_reason = quality_flywheel.modification_reason |
| AC-TG-05 | 置信度 < 0.85 创建新 logical_case | T018, T023, T030 | 单元测试 + 集成测试：低置信度场景创建新 logical_case |

---

## 跨模块依赖说明

| 本模块任务 | 依赖模块 | 依赖任务 | 依赖说明 |
| :--- | :--- | :--- | :--- |
| T004 | platform-api | T025@platform-api | logical_cases / case_versions 表迁移就绪 |
| T039 | platform-api | T030@platform-api | 版本 API（GET /cases/:id/versions）已实现 |
| T040 | platform-api | T030@platform-api | quality_flywheel 双写验证 |

---

## 特殊约束

| 约束 | 说明 |
| :--- | :--- |
| 第一段硬约束 | 禁止修改 `src/testcase_generator/` 目录下任何文件 |
| 第二段启动前提 | 第一段 platform-api + platform-web 交付验证通过 |
| system_id 获取 | 经 `batch.system_id` 取得（test_cases 无此字段） |
| EmbeddingClient.embed_batch | 返回 `list[list[float]]` |
| anchor_method 枚举 | `deterministic` / `embedding` |
| change_type 枚举 | `ai_gen` / `iteration` / `ai_regen` / `requirement_change` / `human_edit` |
| checkpointer | AsyncPostgresSaver（PostgreSQL） |

---

## 任务统计

| 指标 | 数值 |
| :--- | :--- |
| 总任务数 | 40 |
| P0（必须） | 36 |
| P1（重要） | 4 |
| P2（可选） | 0 |
| 可并行任务 | 8 |
| 阶段 1（环境与基础） | 4 |
| 阶段 2（数据层） | 6 |
| 阶段 3（功能实现） | 18 |
| 阶段 4（集成与收尾） | 12 |
