# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 语言规范

- 所有对话和文档使用中文
- 代码注释/docstring 使用中文

## 项目概述

AI 驱动的 QA 智能平台 — 上传需求文档，自动生成测试用例。三个核心模块 + 一个前端：

- `src/platform_api` — FastAPI 后端（REST API、Celery 任务分发、数据持久化）
- `src/testcase_generator` — LangGraph DAG 流水线（主链 parse → comprehend → rule_extract → test_points → write_cases → review → verify → dedup → export；其中 comprehend 有 NO_GO 人工澄清分支、review 按需 `backfill` 回填循环——详见架构关键点）
- `src/knowledge_base` — RAG 知识库（向量/图/混合检索、embedding、MinIO 存储）
- `web/` — React 18 + Ant Design 5 + Zustand 前端

## 常用命令

```bash
# 后端
uv run uvicorn src.platform_api.main:app --reload --port 8000
uv run celery -A src.platform_api.core.celery_app worker -Q testcase_generation,kb_parsing,export --loglevel=info

# 前端
cd web && npm run dev          # localhost:3000, 代理 /api → :8000

# 测试
uv run pytest                  # 全量
uv run pytest tests/testcase_generator/test_grounded_pipeline.py  # 单文件
uv run pytest -k "test_dedup"  # 按名称匹配

# Lint
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/

# 数据库迁移
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "描述"
```

## 架构关键点

### Pipeline（LangGraph StateGraph）

流水线定义在 `src/testcase_generator/pipeline/graph.py`，节点实现在 `src/testcase_generator/stages/` 各子目录的 `node.py`。状态流转通过 `PipelineState`（TypedDict）传递。

关键流程：
- `comprehend` 后经 `gate_router`：GO/CONDITIONAL → `rule_extract`；NO_GO → 独立 `interrupt` 节点（LangGraph `interrupt()` 等待人工澄清），澄清后回 `comprehend` 重新评估
- `rule_extract` 沿 PRD 章节树抽取明示业务规则，产出规则台账（`rule_extract_enabled` 开关控制，关时直通）
- `review` 后经 `review_router`：达标 → `verify`；存在零覆盖/假覆盖测试点 → `backfill`。`backfill` 自循环（`backfill`→`backfill`，**不回 `review`**），定向回填零覆盖（追加）+ 假覆盖（替换），最多 `MAX_RECONCILE=2` 轮后 → `verify`
- `verify` 做事实核验，`dedup` 做规则锚定近重复折叠

### 用例数量控制机制

- **维度信号门控** (`test_points/node.py` `_DIMENSION_GATE`) — 质量属性维度需文档触发词命中才放行
- **内容稀薄阈值** (`_SPARSE_FEATURE_CHAR_THRESHOLD=200`) — 短功能点仅保留核心维度
- **适用性裁剪** (`ApplicabilityFilter`) — 按功能类型过滤维度
- **分批常量**: `_BATCH_MAX_FEATURES=4`（test_points）、`MAX_TPS_PER_BATCH=7`（write_cases）
- **规则锚定去重** (`dedup/clustering.py` `find_duplicates`) — bigram 相似度折叠，带安全护栏

### 规则锚定覆盖（灰度开关）

四个独立开关在 `settings.py` 中，启用顺序有依赖：
1. `rule_extract_enabled` — 规则台账抽取
2. `rule_driven_testpoints_enabled` — 规则驱动测试点（依赖 1）
3. `rule_coverage_gate_enabled` — 覆盖闸 + 定向 backfill（依赖 2）
4. `safe_dedup_enabled` — 规则锚定安全去重（依赖 2）

### 异步任务

Celery 配置在 `src/platform_api/core/celery_app.py`。任务注册：
- `testcase_generator.run_pipeline` — 全流水线
- `knowledge_base.parse_task` — 文档解析入库

`visibility_timeout=21600`（6h）防长任务被误判重投。

### 数据库 Schema

三个 PostgreSQL schema：`public`（系统）、`knowledge`（文档/嵌入）、`testcase`（批次/测试点/用例/规则台账）。迁移在 `alembic/versions/`。

### 前端结构

Vite dev server 端口 3000，`/api` 代理到 8000。页面路由在 `web/src/App.tsx`，状态管理用 Zustand store。

## 测试约定

- `asyncio_mode = "auto"` — 异步测试直接 `async def test_xxx()` 无需装饰器
- 测试目录结构镜像 `src/` 结构
- 集成测试需要 PostgreSQL + Redis；单元测试通过 mock LLM client 跑

## 配置

所有配置通过环境变量加载（`pydantic-settings`），定义在 `src/platform_api/core/settings.py`。复制 `.env.example` 为 `.env` 填入真实值。关键变量：`LLM_BASE_URL`、`LLM_API_KEY`、`LLM_PRIMARY_MODEL`、`DATABASE_URL`。

## 用户公约（产品经理思维）

本用户不懂技术，需求描述未必清晰、未必使用专业术语。

### AI 行为规范
1. **产品经理思维优先** — 收到需求后，先用业务语言复述确认理解，再转化为技术方案落地
2. **听不懂必须问** — 理解不了的地方立即中断，向用户提问确认，不得猜测需求
3. **提问要精准** — 简洁、直接、给出选项，不要让用户解释技术细节
4. **翻译是 AI 的工作** — 不要期待用户提供字段名、接口文档、技术规范；听完业务描述后 AI 自己查
5. **不要闷头干** — 不确定时先问，别等做完了才发现方向错了
