# 会话进度日志 — 架构换代

> 配合 `task_plan.md`（总纲）+ `findings.md`（调研）使用。本文件记录"我做了什么、什么时候、下一步"。

---

## 时间线

### 2026-06-18（换代规划启动）

**已完成：**
1. **v5 审计交付** — 批次 `c1f533e3`（2176 用例）对照漫剧批创 PRD，17-worker 资深级审计，查出 54 个 P0。期间遇到 subagent `resource_exhausted` 与 Cursor `unpaid invoice`，部分 worker（W11/W14/W16）改为手工补审。
2. **8 形态愿景成形** — 调研 2026 行业最佳实践（GraphRAG / Agentic RAG / 多模态 PRD 解析 / semantic diff），综合出 8 大形态。
3. **用户拍板关键决策** — 决策1=A（历史用例废弃）/ 决策2（QA 内部工具）/ 决策3（我架构师、Claude Code 执行）/ 决策4（不计成本）；节奏选 B 渐进式；8 形态全要。
4. **7 个种子健康检查** — 读完 flywheel / iteration / golden_set / few_shot / graph_search / hybrid_search / rule_coverage，结论见 findings.md（大多发芽未连根）。
5. **周期重估** — 纠正最初"5 个月"误估（人月思维），按 vibe coding 改为 6–10 周；明确"比较好的初版用例"=阶段①+②（3-5 周）。
6. **确定第一里程碑** — ①(图解析+GraphRAG) + ②(cheat sheet)，先集中火力。
7. **建立架构师记忆体系** — 创建 `task_plan.md` / `findings.md` / `progress.md` 三文件。
8. **决策7 定案 + 换代前快照** — 决定：平台功能（通知/搜索/用例库/批次管理）保留作体验层地基；生成侧 v5 补丁冻结存档不进新主干（换代用 GraphRAG+cheat sheet 替换）；xspec 忽略。提交全量快照 commit，开新分支 `feat/architecture-migration`。
9. **①地盘侦察完成（3 路并行 explore）** — 关键发现见下，①的 5-chunk 骨架已定。

### ①侦察关键发现（写 plan 的事实依据）
- **图解析切入点**：图片只存 MinIO（`systems/{system_id}/documents/{相对路径}`，不建 documents 行）；`MarkdownParser` 把图 url 提到 `documents.image_refs`，正文保留 `![alt](url)`；parse 阶段读 `documents.content`（DB 字段），**对图"看不到像素"**。`LLMClient`(`src/testcase_generator/services/llm_client.py`)只支持纯文本 `user_content:str`，**不支持多模态/视觉**，settings 无 vision 模型配置。最小侵入路径：在 KB 侧 `ParseService.parse_document`(L25-65) 做"读 MinIO→视觉 LLM 描述→写回 content"，parse_node 不用改。
- **9 feature 丢失根因（精确定位）**：`test_points/node.py` `_BATCH_MAX_FEATURES=4` 按"每批≤4 feature 或 累计 JSON>15000 字符"切批；`_call_batch` 异常返回 None(L342-350) → 整批 feature **零测试点、仅打 error log、无完整性校验、无重试**。对比 write_cases 的 `MAX_TPS_PER_BATCH=7` 用 `_split_by_count` 保证总数不变。
- **GraphRAG 现状**：现有"图"= 文档级 BFS（`document_associations` 表，7 种 relation_type，见 `enums.py DocRelationType`），**非实体级**；`auto_link_on_create`(`linkage_service.py`)已实现但**从未接入**；关联文档检索只取前 200 字；embedding=`text-embedding-3-small`(1536维)+pgvector+HNSW；向量检索在流水线中**从未触发**（parse 不传 query）。
- **规则抽取可复用**：`rule_extract` 已成熟（`load_seed_markdown`→`build_units`章节树切分→`extract_rules` LLM并发抽取→`RuleItem{rule_code/module/rule/source_quote/category}`→落 `testcase.rules`）。GraphRAG 实体抽取可复用这套框架。

### ①的 5-chunk 骨架
- Chunk 0：修 9 feature 丢失 bug（test_points 批失败兜底）+ 图覆盖体检尺子（零风险）
- Chunk 1：LLMClient 多模态扩展 + 图解析关（KB 侧 ParseService 读图→视觉描述→写回 content，灰度开关默认关）
- Chunk 2：实体级知识图谱表 + 抽取落库（复用 rule_extract 框架，新增实体/关系抽取）
- Chunk 3：实体级多跳检索（新建 entity graph traverse + 关系查询接口）
- Chunk 4：接入生成流水线 + 漫剧批创端到端验收

10. **① 完整 plan 已交付** — `docs/plans/2026-06-18-stage1-graph-parse-graphrag.md`（5 chunk / TDD / 灰度开关）。2 前提已答：网关有视觉模型（plan 留 `LLM_VISION_MODEL` 配置）；PRD=1 md(~10w字)+57 图目录(`~/Desktop/漫剧批创初版功能PRD/`)，**md 仅 `![]()` 引用 9 张**，另 48 张界面图需从 MinIO 全集取（已写进 plan 架构决策2 + 决策9：全解析 57 张）。

11. **拆解机器(splitter)软肋确认 + 决策10** — 用户质疑「只用标题拆太死板」，读源码确认：splitter 纯 heading-based（`_HEADING_RE` 只认 `#`），无 `#` 标题 PRD 会令 `build_units` 归零（规则/实体全线 0 产出）。漫剧批创规整 md 不受影响。行业最佳实践=layout-aware 结构优先（方向对）+ 递归分隔符兜底（缺）+ semantic 仅叙述文本（技术 PRD 不必上）。用户决定**加固 defer**，列入 backlog（详见 findings.md 第九节 + task_plan 决策10）。

### 2026-06-18（① 执行 — Claude Code）

**已完成（代码+单测，60 项全绿）：**

12. **Chunk 0 — 零风险止血 + 尺子**
    - Task 0.1 `fix(test-points)`: feature 完整性兜底（批失败重试+单 feature 降级+缺额校验）— 5 单测
    - Task 0.2 `feat(kb)`: 图覆盖体检 CLI `python -m src.knowledge_base.cli.image_coverage_probe` — 4 单测
    - Task 0.3: 需 live DB+MinIO 手工验收（sandbox 网络受限）

13. **Chunk 1 — 图解析关（多模态）**
    - Task 1.1: LLMClient `generate_structured` 支持 `images: list[bytes]`，用 `LLM_VISION_MODEL=claude-opus-4-6` — 4 单测
    - Task 1.2: 图清单收集器 `collect_images`（MinIO 全集 57 张，标注 referenced_in_md + section_hint）— 4 单测
    - Task 1.3: 视觉描述生成器 `caption_images`（并发+失败隔离，ImageCaption schema）— 4 单测
    - Task 1.4: content_injector 归位（md 引用追加图述 / 未引用按 section_hint / 兜底附录）+ parse_service 接入 + migration 017 — 7 单测
    - Task 1.5: 需 live 验收

14. **Chunk 2 — 实体级知识图谱**
    - Task 2.1: migration 018 `knowledge.entities` + `knowledge.entity_relations` + EntityType/EntityRelationType 枚举 + ORM
    - Task 2.2: 实体关系抽取器 `extract_entity_graph`（并发+失败隔离+跨单元 canonical_key 去重）— 4 单测
    - Task 2.3: EntityRepository.save_graph（幂等：先删旧再写新）+ parse_service 接入 entity_graph_enabled — 4 单测
    - Task 2.4: 需 live 验收

15. **Chunk 3 — 实体检索**
    - Task 3.1: `traverse_entities` WITH RECURSIVE BFS（有向边双向展开，保留 relation_type + direction）— 3 单测
    - Task 3.2: `query_entity_context`（名称匹配→多跳→按 relation_type 归类应答）+ entity_retrieval_enabled 开关 — 3 单测
    - Task 3.3: 需 live 验收

16. **Chunk 4 — 接入+默认开**
    - Task 4.1: ParsedContext 新增 `entity_graph_hints: list[dict]`（为②铺路）— 2 单测
    - Task 4.3: 三开关 `image_caption_enabled` / `entity_graph_enabled` / `entity_retrieval_enabled` 默认 True

**提交历史（feat/architecture-migration）：**
- `0f421ba` fix(test-points): feature 完整性兜底
- `bcea2bd` feat(kb): 图覆盖体检 CLI
- `265cabd` feat(llm): generate_structured 支持多模态
- `5c05522` feat(kb): 图清单收集器
- `c1d44ef` feat(kb): 视觉描述生成器
- `0807f75` feat(kb): 图描述归位+持久化（灰度）
- `ad05ee9` feat(db): entities + entity_relations
- `7f93f36` feat(kb): 实体关系抽取器
- `5e8aafc` feat(kb): 实体图谱落库+parse 接入
- `eed55e8` feat(kb): 实体图 BFS 遍历
- `428b558` feat(kb): 关系查询服务
- `f729197` feat(pipeline): parse 挂接 entity_graph_hints
- `a7a1269` feat(stage1): 三开关默认开

**待 live 验收（需 DB+MinIO+视觉模型 running）：**
- Task 0.3: 跑漫剧批创基线（feature 21→30 确认 / 图覆盖率 0%）
- Task 1.5: 开 image_caption_enabled parse → 图覆盖≈100%
- Task 2.4: 开 entity_graph_enabled parse → 实体/关系统计 + 抽查正确率≥80%
- Task 3.3: 3 个 v5 混淆点关系查询应答正确
- Task 4.2: 端到端全流水线 + feature≥30 + 红线对照

**下一步：**
- 在 live 环境跑验收（上述 5 个 Task），填基线表数字
- ① 验收达红线后 → 写 ② cheat sheet 详细 plan
- （Backlog）splitter 加固——通用化/接入非规整 PRD 前必做

---

## 遇到的错误（积累知识，避免重复）

| 错误 | 场景 | 解决方案 |
|---|---|---|
| `resource_exhausted` | 审计 subagent 读全量用例+PRD 超上下文 | 拆小批次 / 拆分大 case 文件 / 让 subagent 选择性读 PRD 章节；仍失败的手工补审 |
| `unpaid invoice` | Cursor 平台账单 | 外部问题，非技术层面可解；导致部分 worker 手工完成 |

---

## 五问重启测试（任何时候能答上=记忆完好）

| 问题 | 答案来源 |
|---|---|
| 我在哪里？ | task_plan.md 第九节「当前状态」 |
| 我要去哪里？ | task_plan.md 第五节「5 阶段路线图」+ 第六节「第一里程碑」 |
| 目标是什么？ | task_plan.md 第二节「北极星目标」 |
| 我学到了什么？ | findings.md（种子检查 + 行业调研 + 54 P0 根因） |
| 我做了什么？ | 本文件时间线 |
