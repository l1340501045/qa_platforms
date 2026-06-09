---
title: "testcase-generator AI Agent 任务清单"
module_type: ai-agent
status: active
date: "2026-06-08"
---

# testcase-generator AI Agent 任务清单

## 文档信息

| 属性 | 内容 |
| :--- | :--- |
| **所属变更** | CHG-20260605-001 |
| **模块名称** | testcase-generator |
| **模块类型** | ai-agent |
| **创建时间** | 2026-06-08 |

---

## 任务格式

```
- [x] T{NNN} [P?] {优先级} 任务描述（含具体文件路径）
  depends: T{NNN}, T{NNN}@{other-module}
```

| 标记 | 含义 |
| :--- | :--- |
| `T{NNN}` | 模块内唯一编号，从 T001 起编 |
| `[P]` | 可并行：操作不同文件、无依赖未完成任务 |
| 优先级 | P0（必须）/ P1（重要）/ P2（可选） |
| `depends:` | 依赖标注（缩进换行）。模块内：`T010`；跨模块：`T020@platform-api`。无依赖则不写此行 |

---

## 阶段 1：环境与基础

**目标**：项目骨架、依赖、Pydantic schema、维度库、信任配置就绪

- [x] T001 [P] P0 项目结构初始化，创建 `src/testcase_generator/__init__.py`、`stages/`、`schemas/`、`services/`、`tasks/`、`config/` 目录
- [x] T002 [P] P0 依赖安装与 `pyproject.toml` 更新（langgraph, langgraph-checkpoint-redis, pydantic, celery, redis, playwright）`pyproject.toml`
- [x] T003 [P] P0 Pydantic schema：ParsedContext（信源清单 + 文档结构）`src/testcase_generator/schemas/parsed_context.py`
- [x] T004 [P] P0 Pydantic schema：ComprehensionReport（理解矩阵 + 盲区列表）`src/testcase_generator/schemas/comprehension_report.py`
- [x] T005 [P] P0 Pydantic schema：TestPoint（维度 + 覆盖项 + 优先级）`src/testcase_generator/schemas/test_point.py`
- [x] T006 [P] P0 Pydantic schema：TestCase（步骤 + 预期 + provenance + 可信度）`src/testcase_generator/schemas/test_case.py`
- [x] T007 [P] P0 Pydantic schema：AuditReport（覆盖矩阵 + 缺失维度 + 补全建议）`src/testcase_generator/schemas/audit_report.py`
- [x] T008 [P] P0 维度库初始化（dimensions.yaml + 适用性矩阵定义）`src/testcase_generator/config/dimensions.yaml`
- [x] T009 [P] P0 信任顺序配置（信源优先级 + 冲突解决策略）`src/testcase_generator/config/trust_order.yaml`
- [x] T010 [P] P1 结构化日志配置（trace_id + stage 标注）`src/testcase_generator/logging.py`

**✓ 检查点**：`import src.testcase_generator` 成功，所有 schema 可实例化，维度库加载无报错

---

## 阶段 2：数据层

**目标**：接入共享 models、LangGraph state、Redis checkpoint 就绪

- [x] T011 P0 接入 platform-api 共享 models 包（import platform_api.models.testcase，配置数据库 session）`src/testcase_generator/db.py`
  depends: T002, T017@platform-api
- [x] T012 P0 编写 testcase Repository 层（基于共享 models 操作 testcase schema：BatchRepository, CaseRepository, PointRepository, ArtifactRepository, FlywheelRepository, GoldenSetRepository）`src/testcase_generator/repositories/`
  depends: T011
- [x] T013 P0 LangGraph state schema（TypedDict：PipelineState 含各阶段产物字段）`src/testcase_generator/schemas/pipeline_state.py`
  depends: T003, T004, T005, T006, T007
- [x] T014 P0 Redis checkpoint 配置（RedisSaver 初始化 + 连接池）`src/testcase_generator/services/checkpoint.py`
  depends: T002

**✓ 检查点**：共享 models 可 import，PipelineState TypedDict 类型检查通过，Redis 连接正常

---

## 阶段 3：功能实现

**目标**：6 阶段流水线各节点实现 + LangGraph 编排完成

### Stage 1：parse（AC-01）

- [x] T015 P0 文档解析节点：输入预处理 + 结构化拆分 `src/testcase_generator/stages/parse/node.py`
  depends: T013, T003
- [x] T016 P0 信源清单构建（按信任顺序排列 + 来源标注）`src/testcase_generator/stages/parse/source_registry.py`
  depends: T009, T015
- [x] T017 P1 Playwright MCP 集成（可选：动态页面抓取辅助）`src/testcase_generator/stages/parse/playwright_fetch.py`
  depends: T015
- [x] T018 P0 knowledge-base 检索调用（调用共享 knowledge_base.services.retrieval_service 获取关联上下文，进程内直接 import）`src/testcase_generator/stages/parse/kb_retriever.py`
  depends: T015, T018@knowledge-base

### Stage 2：comprehend + Gate

- [x] T019 P0 理解矩阵生成节点（功能点提取 + 业务规则识别）`src/testcase_generator/stages/comprehend/node.py`
  depends: T013, T004
- [x] T020 P0 盲区识别（信息缺失检测 + 矛盾点标记）`src/testcase_generator/stages/comprehend/blind_spot_detector.py`
  depends: T019
- [x] T021 P0 Gate 判定逻辑（GO / CONDITIONAL / NO_GO 规则引擎）`src/testcase_generator/stages/comprehend/gate.py`
  depends: T019, T020
- [x] T022 P0 interrupt() 挂起实现（NO_GO/CONDITIONAL 时暂停等待人工输入）`src/testcase_generator/stages/comprehend/interrupt_handler.py`
  depends: T021, T014

### Stage 3：test-points（AC-02）

- [x] T023 P0 维度矩阵驱动的测试点生成 `src/testcase_generator/stages/test_points/node.py`
  depends: T013, T005, T008
- [x] T024 P0 适用性裁剪（根据文档类型 + 上下文过滤不适用维度）`src/testcase_generator/stages/test_points/applicability_filter.py`
  depends: T023, T008
- [x] T025 P0 漏测强制维度注入（确保关键维度不被遗漏）`src/testcase_generator/stages/test_points/mandatory_dimensions.py`
  depends: T024

### Stage 4：write-cases（AC-03, AC-04）

- [x] T026 P0 用例展开节点（TestPoint → TestCase 映射）`src/testcase_generator/stages/write_cases/node.py`
  depends: T013, T006, T025
- [x] T027 P0 provenance 标注（每条用例追溯到信源段落）`src/testcase_generator/stages/write_cases/provenance_tagger.py`
  depends: T026, T016
- [x] T028 P0 可信度标注（基于信源信任等级计算 confidence score）`src/testcase_generator/stages/write_cases/confidence_scorer.py`
  depends: T026, T009
- [x] T029 P0 few-shot 注入（从质量飞轮提取高质量样本作为示例）`src/testcase_generator/stages/write_cases/few_shot_injector.py`
  depends: T026

### Stage 5：review-cases（AC-05）

- [x] T030 P0 覆盖审计节点（用例集 vs 测试点覆盖矩阵比对）`src/testcase_generator/stages/review/node.py`
  depends: T013, T007, T026
- [x] T031 P0 缺失维度补全（自动补充遗漏维度的用例）`src/testcase_generator/stages/review/gap_filler.py`
  depends: T030

### Stage 6：export

- [x] T032 [P] P0 YAML 导出格式定义与序列化 `src/testcase_generator/stages/export/yaml_exporter.py`
  depends: T026
- [x] T033 [P] P0 Markdown 视图导出（人可读测试报告格式）`src/testcase_generator/stages/export/markdown_exporter.py`
  depends: T026
- [x] T034 P0 导出节点编排（双轨并行输出）`src/testcase_generator/stages/export/node.py`
  depends: T032, T033

### LangGraph 编排

- [x] T035 P0 StateGraph 组装（6 阶段节点注册 + 条件边定义）`src/testcase_generator/pipeline/graph.py`
  depends: T015, T019, T023, T026, T030, T034
- [x] T036 P0 条件边实现（Gate 结果路由 + review 迭代循环边）`src/testcase_generator/pipeline/edges.py`
  depends: T035, T021
- [x] T037 P0 RedisSaver 集成（checkpoint 持久化 + 恢复）`src/testcase_generator/pipeline/persistence.py`
  depends: T035, T014
- [x] T038 P0 端到端流水线集成验证 `src/testcase_generator/pipeline/runner.py`
  depends: T035, T036, T037

**✓ 检查点**：流水线端到端运行通过（parse → export），Gate 挂起/恢复正常，checkpoint 可恢复

---

## 阶段 4：集成与收尾

**目标**：Celery 集成、迭代能力、落库、质量飞轮、评估框架、测试覆盖

- [x] T039 P0 Celery Worker 配置与任务定义（启动流水线 / 挂起 / 恢复）`src/testcase_generator/tasks/pipeline_task.py`
  depends: T038
- [x] T040 P0 Celery 任务状态回调（进度通知 + 异常上报）`src/testcase_generator/tasks/callbacks.py`
  depends: T039
- [x] T041 P0 Review 迭代：基于人工反馈重跑 write-cases 阶段（AC-05, AC-06）`src/testcase_generator/services/iteration_service.py`
  depends: T038, T036
- [x] T042 P0 落库逻辑：确认后写入正式 test_cases 表 + 调用共享 knowledge_base.services.linkage_service 自动建立关联（AC-07）`src/testcase_generator/services/persist_service.py`
  depends: T012, T020@knowledge-base
- [x] T043 P0 质量飞轮：三元组存储（问题类型-维度-优质用例）`src/testcase_generator/services/flywheel_service.py`
  depends: T012, T029
- [x] T044 P0 few-shot 提取服务（从飞轮库中按相似度选取样本）`src/testcase_generator/services/few_shot_retriever.py`
  depends: T043
- [x] T045 P0 Golden-set 评估框架搭建（标准集定义 + 自动评分 pipeline）`src/testcase_generator/services/golden_set_evaluator.py`
  depends: T038
- [x] T046 [P] P0 Stage 单元测试（parse, comprehend, test-points, write-cases, review, export）`tests/testcase_generator/unit/test_stages.py`
  depends: T015, T019, T023, T026, T030, T034
- [x] T047 [P] P0 Pipeline 单元测试（graph 组装 + 条件边路由）`tests/testcase_generator/unit/test_pipeline.py`
  depends: T035, T036
- [x] T048 P0 集成测试：完整流水线端到端（输入文档 → 导出用例）`tests/testcase_generator/integration/test_full_pipeline.py`
  depends: T038, T039
- [x] T049 [P] P1 Celery 任务集成测试（挂起/恢复/超时）`tests/testcase_generator/integration/test_celery_tasks.py`
  depends: T039, T040
- [x] T050 [P] P1 API 文档补全（OpenAPI schema 注释）`src/testcase_generator/api/`
  depends: T010

**✓ 检查点**：单元测试覆盖率 ≥ 80%，集成测试全链路通过，Celery 挂起/恢复正常，质量飞轮写入成功

---

## 跨模块依赖说明

| 本模块任务 | 依赖模块 | 依赖说明 |
| :--- | :--- | :--- |
| T011 | T017@platform-api | 接入 platform-api 共享 models 包 |
| T018 | T018@knowledge-base | parse 阶段进程内调用 knowledge-base RetrievalService 获取关联上下文 |
| T042 | T020@knowledge-base | 落库时进程内调用 knowledge-base linkage_service 自动建立关联 |
| T039 | T026@platform-api | Celery 任务由 platform-api 生成编排 service 触发 |

---

## 任务统计

| 指标 | 数值 |
| :--- | :--- |
| 总任务数 | 50 |
| P0（必须） | 46 |
| P1（重要） | 4 |
| P2（可选） | 0 |
| 可并行任务 | 12 |
| 预计工时 | 70h |
