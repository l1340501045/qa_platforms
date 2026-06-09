# platform-api 后端任务清单

## 文档信息

| 属性 | 内容 |
| :--- | :--- |
| **所属变更** | CHG-20260605-001 |
| **模块名称** | platform-api |
| **模块类型** | web-backend |
| **创建时间** | 2026-06-08 |

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
| `depends:` | 依赖标注（缩进换行）。模块内：`T010`；跨模块：`T020@knowledge-base`。无依赖则不写此行 |

---

## 阶段 1：环境与基础

**目标**：项目结构、依赖、中间件、公共工具就绪

- [x] T001 [P] P0 项目结构初始化，创建 `src/platform_api/` 包目录及子模块（api/ services/ models/ repositories/ schemas/ middlewares/ utils/ tasks/）
- [x] T002 [P] P0 依赖安装，编写 `pyproject.toml`（fastapi, uvicorn, sqlalchemy[asyncio], asyncpg, celery[redis], redis, minio, pydantic-settings, alembic, python-multipart）
- [x] T003 [P] P0 配置管理模块 `src/platform_api/core/settings.py`（Pydantic BaseSettings，环境变量加载：DB_URL, REDIS_URL, MINIO_* 等）
- [x] T004 P0 FastAPI app 骨架 + 中间件链（请求ID、CORS、限流、日志、全局错误处理）`src/platform_api/main.py` + `src/platform_api/middlewares/`
- [x] T005 P0 Celery 配置 + Redis broker 连接 `src/platform_api/core/celery_app.py`
- [x] T006 P0 MinIO 客户端初始化与工具封装 `src/platform_api/core/minio_client.py`
- [x] T007 P0 数据库连接与 async session 工厂 `src/platform_api/core/database.py`
  depends: T003

**✓ 检查点**：`uvicorn src.platform_api.main:app` 可启动，`/health` 返回 200

---

## 阶段 2：数据层

**目标**：数据库表结构、迁移脚本、SQLAlchemy models 与基础 Repository 就绪

- [x] T008 P0 Alembic 初始化 + 三 schema 创建迁移（public + knowledge + testcase）`alembic/` + `alembic/versions/001_create_schemas.py`
  depends: T007
- [x] T009 P0 public schema 表迁移（systems → system_associations），按 `platform-api/data-model.md` 中对应表定义实现 `alembic/versions/002_public_tables.py`
  depends: T008
- [x] T010 P0 knowledge schema 表迁移（documents → document_associations → document_embeddings → prototype_links），按 `platform-api/data-model.md` 中 `knowledge.*` 表定义实现 `alembic/versions/003_knowledge_tables.py`
  depends: T008
- [x] T011 P0 testcase schema 表迁移（test_batches → test_points → test_cases → stage_artifacts → quality_flywheel → golden_set_results → export_tasks），按 `platform-api/data-model.md` 中 `testcase.*` 表定义实现 `alembic/versions/004_testcase_tables.py`
  depends: T008
- [x] T012 [P] P0 SQLAlchemy models — public schema `src/platform_api/models/public.py`（System, SystemAssociation），按 `platform-api/data-model.md` 中对应表定义实现
  depends: T009
- [x] T013 [P] P0 SQLAlchemy models — knowledge schema `src/platform_api/models/knowledge.py`（Document, DocumentAssociation, DocumentEmbedding, PrototypeLink），按 `platform-api/data-model.md` 中 `knowledge.*` 表定义实现
  depends: T010
- [x] T014 [P] P0 SQLAlchemy models — testcase schema `src/platform_api/models/testcase.py`（TestBatch, TestPoint, TestCase, StageArtifact, QualityFlywheel, GoldenSetResult, ExportTask），按 `platform-api/data-model.md` 中 `testcase.*` 表定义实现
  depends: T011
- [x] T015 P0 基础 Repository 层 — BaseRepository + 分 schema 实现 `src/platform_api/repositories/base.py`
  depends: T012, T013, T014
- [x] T016 [P] P0 索引迁移脚本（全部索引，含 pgvector HNSW），按 `platform-api/data-model.md` 索引设计实现 `alembic/versions/005_create_indexes.py`
  depends: T009, T010, T011
- [x] T017 P0 共享 models 包导出配置（将 models/ 作为可被 knowledge-base、testcase-generator 导入的共享包）`src/platform_api/models/__init__.py`
  depends: T012, T013, T014

**✓ 检查点**：`alembic upgrade head` 成功，全部表和索引创建完毕，模型可加载，共享包可被其他模块 import

---

## 阶段 3：功能实现

**目标**：按功能域实现核心业务逻辑和 API

### 系统管理 — AC-01 (P0)

**目标**：系统 CRUD + 系统间关联配置
**独立验证**：POST/GET/PUT/DELETE `/api/v1/systems` 正确响应；系统关联 CRUD 正常
**对应验收标准**：AC-01

- [x] T018 P0 系统管理 Pydantic schemas `src/platform_api/schemas/system.py`
  depends: T012
- [x] T019 P0 系统管理 service 层（CRUD + 关联管理 + 名称唯一约束校验）`src/platform_api/services/system_service.py`
  depends: T015, T018
- [x] T020 P0 系统管理 API（系统 CRUD + 关联 CRUD 7 个端点）`src/platform_api/api/v1/systems.py`
  depends: T019, T004

**✓ 检查点**：系统管理全部端点可独立调用和测试

---

### 文档管理 — AC-02, AC-03, AC-09 (P0)

**目标**：文件夹上传/解压/存 MinIO/创建 documents 行（metadata + storage_path）/文档关联/触发 KB 解析
**独立验证**：POST `/api/v1/systems/:id/documents/batch` 上传 zip → 文档入库 → MinIO 可访问
**对应验收标准**：AC-02, AC-03, AC-09

- [x] T021 P0 文档管理 Pydantic schemas `src/platform_api/schemas/document.py`
  depends: T013
- [x] T022 P0 文件上传 service（zip 解压/文件过滤/MinIO 上传/创建 documents 行含 metadata + storage_path/触发 KB 解析任务）`src/platform_api/services/document_service.py`
  depends: T015, T006, T005, T021
- [x] T023 P0 文档关联 service（创建/查询/图遍历 WITH RECURSIVE）`src/platform_api/services/doc_association_service.py`
  depends: T015, T021
- [x] T024 P0 文档管理 API（批量上传/列表/详情/删除/关联 CRUD）`src/platform_api/api/v1/documents.py`
  depends: T022, T023, T004

**✓ 检查点**：文件夹 zip 上传后文档可查、MinIO 可下载、关联图遍历正常

---

### 用例生成编排 — AC-04 (P0)

**目标**：Celery 任务发布/状态轮询/阶段进度回调/Gate NO_GO 挂起恢复
**独立验证**：POST `/api/v1/documents/:id/generate` → 批次创建 → Celery 任务发布 → GET 批次可查状态
**对应验收标准**：AC-04

- [x] T025 P0 批次管理 Pydantic schemas `src/platform_api/schemas/batch.py`
  depends: T014
- [x] T026 P0 生成编排 service（触发生成/状态查询/Redis 进度读取/Gate 挂起检测）`src/platform_api/services/generation_service.py`
  depends: T015, T005, T025
- [x] T027 P0 澄清 service（提交答案/写入 Redis List/恢复 Celery 任务）`src/platform_api/services/clarification_service.py`
  depends: T015, T005, T025
- [x] T028 P0 阶段进度回调接收（Worker → API 回调更新 stage_artifacts）`src/platform_api/api/v1/callbacks.py`
  depends: T026, T004
- [x] T029 P0 批次 API（获取批次详情/触发生成/提交澄清/触发迭代/落库）`src/platform_api/api/v1/batches.py`
  depends: T026, T027, T004

**✓ 检查点**：生成任务可触发、进度可轮询、Gate 挂起可恢复

---

### Review 操作 — AC-05, AC-06, AC-07 (P0)

**目标**：单条 review/批量 review/触发迭代/落库确认
**独立验证**：PATCH `/api/v1/testcases/:id/review` → 状态变更；POST archive → 批次归档
**对应验收标准**：AC-05, AC-06, AC-07

- [x] T030 P0 用例 review Pydantic schemas `src/platform_api/schemas/testcase.py`
  depends: T014
- [x] T031 P0 Review service（单条 review/状态流转/迭代触发/落库 + quality_flywheel 写入）`src/platform_api/services/review_service.py`
  depends: T015, T005, T030
- [x] T032 P0 用例 review API（PATCH review 单条 + 批次迭代/落库复用 batches API）`src/platform_api/api/v1/testcases.py`
  depends: T031, T004

**✓ 检查点**：用例 review 全流程（confirm/modify/delete → iterate → archive）可走通

---

### 导出功能 — AC-08 (P1)

**目标**：异步导出任务/格式转换（Markdown/Excel）/文件下载
**独立验证**：POST `/api/v1/exports` → 导出任务创建 → 完成后 file_url 可下载
**对应验收标准**：AC-08

- [x] T033 P1 导出 Pydantic schemas `src/platform_api/schemas/export.py`
  depends: T014
- [x] T034 P1 导出 Celery 任务（查询已归档用例/生成 Markdown or Excel/上传 MinIO）`src/platform_api/tasks/export_task.py`
  depends: T015, T006, T005, T033
- [x] T035 P1 导出 API（创建导出/查询详情/列表）`src/platform_api/api/v1/exports.py`
  depends: T034, T004

**✓ 检查点**：导出任务可创建、执行完成后文件可下载

---

## 阶段 4：集成与收尾

**目标**：Worker 集成、API 测试、性能与安全验证

- [x] T036 P0 与 knowledge-base Worker 集成（文档上传后发布解析任务到 Celery、接收完成回调更新 embedding_status）`src/platform_api/tasks/kb_integration.py`
  depends: T022, T022@knowledge-base
- [x] T037 P0 与 testcase-generator Worker 集成（生成任务消息格式对齐、进度回调处理）`src/platform_api/tasks/tg_integration.py`
  depends: T026, T039@testcase-generator
- [x] T038 P1 API 集成测试 — 系统管理流程 `tests/integration/test_systems.py`
  depends: T020
- [x] T039 P1 API 集成测试 — 文档上传 + 生成 + review + 落库全流程 `tests/integration/test_generation_flow.py`
  depends: T024, T029, T032
- [x] T040 P1 API 集成测试 — 导出功能 `tests/integration/test_export.py`
  depends: T035
- [ ] T041 [P] P2 性能验证（P95 < 2s，批次详情查询/文档列表分页/并发生成触发）`tests/performance/test_performance.py`
  depends: T029, T024
- [ ] T042 [P] P2 日志与监控完善（结构化日志格式、请求链路 trace_id、关键操作审计日志）`src/platform_api/middlewares/logging.py`
  depends: T004

**✓ 检查点**：全部接口测试通过，Worker 集成正常，P95 < 2s

---

## 交付策略

### MVP 优先（仅 P0）
1. 完成阶段 1 + 阶段 2（基础设施）
2. 完成系统管理 → 文档管理 → 生成编排 → Review 操作
3. 叠加导出功能（P1）和性能优化（P2）

### 功能域间依赖
- 系统管理：无依赖（可独立交付）
- 文档管理：依赖系统存在 + MinIO + Celery
- 生成编排：依赖文档存在 + Celery + Redis
- Review：依赖批次存在
- 导出：依赖已归档用例

---

## 任务统计

| 指标 | 数值 |
| :--- | :--- |
| 总任务数 | 42 |
| P0（必须） | 36 |
| P1（重要） | 4 |
| P2（可选） | 2 |
| 可并行任务 | 8 |
| 预计工时 | 46h |
