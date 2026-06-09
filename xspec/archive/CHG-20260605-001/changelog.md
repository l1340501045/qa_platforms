# 变更记录 — CHG-20260605-001 知识库搭建与AI用例生成核心闭环

## 基本信息

| 属性 | 内容 |
| :--- | :--- |
| **变更编号** | CHG-20260605-001 |
| **变更名称** | 知识库搭建与AI用例生成核心闭环 |
| **归档时间** | 2026-06-09 |

## 变更概述

搭建按系统维度组织的知识库，实现 Agent Skills/RAG 智能检索，AI 基于完整上下文生成资深级测试用例，支持 review 迭代落库和导出。包含完整的前后端实现、数据库设计、AI Pipeline 编排、以及前后端联调验证。

## 涉及模块

| 模块 | 操作 | 说明 |
| :--- | :--- | :--- |
| knowledge-base | 新增 | 知识库子系统（文档解析、向量化嵌入、图谱检索、混合搜索） |
| testcase-generator | 新增 | AI 用例生成引擎（6阶段 LangGraph Pipeline、Gate 澄清、质量飞轮） |
| platform-api | 新增 | 后端服务（28 个 REST API 端点、统一信封、分页、错误处理） |
| platform-web | 新增 | 前端界面（5 个功能页面、状态机轮询、Gate 交互、Review 工作流） |

## 关键决策

- **架构选型**：单仓多模块（monorepo），3 个后端子系统 + 1 个前端 SPA
- **数据库设计**：3 个 PostgreSQL schema（public/knowledge/testcase）+ pgvector 向量检索
- **AI Pipeline**：LangGraph StateGraph + Redis Checkpoint 持久化，支持中断恢复
- **API 契约**：统一信封 `{code, message, data}`、page/per_page 分页、error_code 错误码
- **前端状态机**：Zustand store + 轮询机制，completed 作为中间态继续轮询至 pending_review
- **Gate 机制**：NO_GO 时 Pipeline 挂起（interrupt），前端自动弹窗澄清，提交后恢复
- **质量飞轮**：人工 review 修改自动沉淀为 few-shot 样本，迭代提升生成质量

## 制品清单

- [x] change.yaml — 变更元数据 + 功能范围边界
- [x] brainstorm.md — 头脑风暴记录
- [x] integration.md — 跨模块协调视图
- [x] knowledge-base/spec.md — 知识库需求规范
- [x] knowledge-base/hld.md — 知识库概要设计
- [x] knowledge-base/design.md — 知识库详细设计
- [x] knowledge-base/data-model.md — 知识库数据模型
- [x] knowledge-base/evaluation.md — 知识库评估方案
- [x] knowledge-base/task.md — 知识库任务清单（27/27 完成）
- [x] testcase-generator/spec.md — 生成器需求规范
- [x] testcase-generator/hld.md — 生成器概要设计
- [x] testcase-generator/design.md — 生成器详细设计
- [x] testcase-generator/data-model.md — 生成器数据模型
- [x] testcase-generator/evaluation.md — 生成器评估方案
- [x] testcase-generator/task.md — 生成器任务清单（51/51 完成）
- [x] platform-api/spec.md — API 需求规范
- [x] platform-api/hld.md — API 概要设计
- [x] platform-api/design.md — API 详细设计
- [x] platform-api/data-model.md — API 数据模型
- [x] platform-api/contracts.md — API 接口契约（v1.2）
- [x] platform-api/task.md — API 任务清单（40/42 完成，2 个 P2 可选未实现）
- [x] platform-web/spec.md — 前端需求规范
- [x] platform-web/hld.md — 前端概要设计
- [x] platform-web/design.md — 前端详细设计
- [x] platform-web/data-model.md — 前端数据模型
- [x] platform-web/contracts.md — 前端接口契约
- [x] platform-web/task.md — 前端任务清单（48/48 完成）
