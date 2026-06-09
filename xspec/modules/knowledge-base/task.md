---
title: "knowledge-base AI Agent 任务清单"
module_type: ai-agent
status: active
date: "2026-06-08"
---

# knowledge-base AI Agent 任务清单

注：knowledge-base 在 CATALOG 中注册为 ai-agent 类型（保持 xflow 兼容），但实际是结构化数据服务层，不含 Agent/LLM 推理。

## 文档信息

| 属性 | 内容 |
| :--- | :--- |
| **所属变更** | CHG-20260605-001 |
| **模块名称** | knowledge-base |
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

**目标**：项目骨架、依赖、配置、公共模型就绪

- [x] T001 [P] P0 项目结构初始化，创建 `src/knowledge_base/__init__.py`、`services/`、`repositories/`、`schemas/` 目录（注意：无 `api/` 目录，KB 不暴露 HTTP 端点）
- [x] T002 [P] P0 依赖安装与 `pyproject.toml` 更新（pgvector, httpx, minio，不含 fastapi）`pyproject.toml`
- [x] T003 [P] P0 配置文件定义（database DSN、MinIO endpoint、Embedding API base_url）`src/knowledge_base/config.py`
- [x] T004 [P] P0 Pydantic 公共模型定义（DocumentDTO, AssociationDTO, SearchRequest, SearchResult）`src/knowledge_base/schemas/common.py`
- [x] T005 [P] P1 结构化日志配置（trace_id 传播）`src/knowledge_base/logging.py`

**✓ 检查点**：`import src.knowledge_base` 成功，配置加载无报错，Pydantic schema 可序列化

---

## 阶段 2：数据层

**目标**：接入 platform-api 共享 models，完成 Repository 层与 Service 层基础

- [x] T006 P0 接入 platform-api 共享 models 包（import platform_api.models.knowledge，配置数据库 session 复用）`src/knowledge_base/db.py`
  depends: T003, T017@platform-api
- [x] T007 P0 编写 knowledge-base Repository 层（基于共享 models 操作 knowledge schema：DocumentRepository, AssociationRepository, EmbeddingRepository，含 CTE 递归查询和向量相似度查询）`src/knowledge_base/repositories/`
  depends: T006
- [x] T008 P0 编写 knowledge-base Service 层基础（DocumentService, AssociationService 的 CRUD 逻辑）`src/knowledge_base/services/base_services.py`
  depends: T007

**✓ 检查点**：Repository 层可正常操作 knowledge schema 表，Service 层 CRUD 可调用

---

## 阶段 3：功能实现

**目标**：按用户故事实现核心业务逻辑

### US-01：文档解析与内容填充

- [x] T009 P0 Markdown 解析器（提取正文 + 图片链接 + front-matter 元数据）`src/knowledge_base/services/parsers/markdown_parser.py`
  depends: T004
- [x] T010 P0 图片提取与 MinIO 上传服务 `src/knowledge_base/services/storage/minio_service.py`
  depends: T003
- [x] T011 P0 文档解析编排服务（读取 documents → 解析 md 内容 → 填充 content/image_refs/content_hash → 更新记录 → 解析完成后自动触发向量化 pipeline）`src/knowledge_base/services/parse_service.py`
  depends: T007, T009, T010
- [x] T012 [P] P1 解析进度回调（Celery task 状态更新）`src/knowledge_base/tasks/parse_task.py`
  depends: T011

### US-02：文档关联管理（AC-03）

- [x] T013 P0 关联建立/删除 Service `src/knowledge_base/services/association_service.py`
  depends: T008
- [x] T014 P0 邻接表 + CTE 遍历查询（N 层深度关联子图获取）`src/knowledge_base/services/graph_traversal.py`
  depends: T007

### US-03：智能检索（AC-04, AC-05）

- [x] T015 P0 关联图遍历检索策略（从种子文档出发，BFS 扩展相关文档）`src/knowledge_base/services/search/graph_search.py`
  depends: T014
- [x] T016 P0 向量召回检索（pgvector cosine similarity + top-k）`src/knowledge_base/services/search/vector_search.py`
  depends: T007
- [x] T017 P0 混合检索编排（图遍历优先 → 向量降级 → 结果融合排序）`src/knowledge_base/services/search/hybrid_search.py`
  depends: T015, T016
- [x] T018 P0 RetrievalService（统一检索入口，供进程内调用）`src/knowledge_base/services/retrieval_service.py`
  depends: T017
- [x] T019 P0 跨系统检索适配器接口定义 `src/knowledge_base/services/search/external_adapter.py`
  depends: T003

### US-04：知识沉淀（内部接口）

- [x] T020 P0 落库时自动建立用例→需求关联 Service `src/knowledge_base/services/linkage_service.py`
  depends: T013, T007

**✓ 检查点**：各 US 对应服务返回正确结果，关联图遍历结果符合预期，RetrievalService 可被进程内调用

---

## 阶段 4：集成与收尾

**目标**：向量化服务完成、测试覆盖达标、性能验证通过

- [x] T021 P0 OpenAI Embedding 调用封装（批量分片 + 重试 + 限流）`src/knowledge_base/services/embedding/embedding_client.py`
  depends: T003
- [x] T022 P0 文档向量化 pipeline（分块 → 调用 Embedding → 写入 pgvector → 更新 embedding_status）。注意：parse_service 完成后自动触发 vectorize_pipeline `src/knowledge_base/services/embedding/vectorize_pipeline.py`
  depends: T021, T007
- [x] T023 [P] P0 Repository 层单元测试 `tests/knowledge_base/unit/test_repositories.py`
  depends: T007
- [x] T024 [P] P0 Service 层单元测试 `tests/knowledge_base/unit/test_services.py`
  depends: T011, T013, T017
- [x] T025 P0 集成测试：解析→向量化→检索全链路 `tests/knowledge_base/integration/test_parse_to_search.py`
  depends: T022, T018
- [x] T026 P1 性能验证：检索 P95 < 5s 基准测试 `tests/knowledge_base/performance/test_search_latency.py`
  depends: T025

**✓ 检查点**：单元测试覆盖率 ≥ 80%，集成测试全链路通过，检索 P95 < 5s

---

## 任务统计

| 指标 | 数值 |
| :--- | :--- |
| 总任务数 | 26 |
| P0（必须） | 23 |
| P1（重要） | 3 |
| P2（可选） | 0 |
| 可并行任务 | 7 |
| 预计工时 | 36h |
