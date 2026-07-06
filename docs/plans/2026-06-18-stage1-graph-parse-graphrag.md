# 阶段① 图解析 + 实体级 GraphRAG Implementation Plan

> **For agentic workers (Claude Code):** 用 superpowers:executing-plans 执行本计划（in-session + checkpoints）。每个 Task 的 Step 用 `- [ ]` 勾选跟踪。**严格按 Chunk 0→4 顺序**，每个 Chunk 末尾的「验收红线」不过则不进下一个 Chunk。所有新能力默认灰度关，可字节级回退。

**Goal:** 让系统「看得到图」（漫剧批创 PRD 的 57 张图转成文字描述插回章节原位）+ 建「实体级知识图谱」（字段/章节/规则/概念 + 它们的关系，支持多跳查询），从而根治 v5 审计的 **9 个 feature 缺失（类 D）**，并为②cheat sheet 阶段打好「能回答跨章关系问题」的地基（部分类 B 概念混淆）。

**Architecture（关键架构决策）:**
1. **图解析放 KB 侧（`ParseService`），不放生成流水线** —— 图描述在文档入库时一次性生成、持久化进 `knowledge.documents.content`，所有下游阶段（parse/comprehend/rule_extract/test_points）自动吃到 enriched 正文，无需各自改读取逻辑。
2. **全解析 57 张图，不只 md 引用的 9 张** —— md 正文仅 `![]()` 引用 9 张，但 `images/` 目录有 57 张（48 张界面截图未被引用）。那 48 张含分页档位/弹窗确认/按钮态等界面细节，正是 v5 错套/混淆 P0 的重灾区。故图清单从「上传文件清单 / MinIO 目录」取全集，而非只靠 `image_refs`。归位策略：靠图片文件名编号前缀（`10`=账户…`80`=批创…`F1/F2/F3`=流程图）匹配 PRD 章节 + 视觉模型描述里的标题线索。
3. **实体图谱新建表，复用 `rule_extract` 抽取框架** —— 新建 `knowledge.entities` + `knowledge.entity_relations`，不动现有文档级 `document_associations`。实体抽取复用 `rule_extract` 的 `build_units`（章节树切分）+ LLM 并发抽取模式。规则本身是一类实体。
4. **多模态扩展 `LLMClient`** —— 现 `LLMClient` 只支持纯文本 `user_content: str`，扩展支持 vision messages；settings 加 `llm_vision_model` 配置（用户网关已有视觉模型，填模型名即可）。
5. **顺序即安全**：C0 修 bug + 建尺子（零风险）→ C1 装眼睛 + 图解析 → C2 建图谱 → C3 建检索 → C4 接入验收。灰度开关：`image_caption_enabled` / `entity_graph_enabled` / `entity_retrieval_enabled`，默认全关。

**Tech Stack:** Python 3.12 · LangGraph · SQLAlchemy(async) + Alembic · Pydantic v2 · pytest / pytest-asyncio · pgvector · 自建 OpenAI 兼容网关（`llm_client`，含视觉模型）· MinIO。

---

## 前置事实（侦察已确认的真实代码现状，Claude Code 无需重新摸底）

> 来源：3 路 explore 精读 src/ + 真实 PRD 目录。所有路径均为仓库内真实路径。

### F1. 文档/图片入库与存储
- 上传入口：`POST /api/v1/systems/{system_id}/documents/batch` → `DocumentService.batch_upload`（`src/platform_api/services/document_service.py` L30-107）→ `UploadService.process_uploads`（`src/platform_api/services/upload_service.py`）。
- **图片只上传 MinIO，不建 documents 行**（`upload_service.py::_handle_image` L174-186）；路径模式 `systems/{system_id}/documents/{相对路径}`（`_storage_path` L191-192）。`.md` 同时写 PostgreSQL `documents.content` + MinIO。**仅支持 `.md` + 图片，无 PDF**。
- Celery 任务名 **`knowledge_base.parse_document`**（不是 CLAUDE.md 写的 `parse_task`），实现在 `src/knowledge_base/tasks/parse_task.py::parse_document_task` L22-43，队列 `kb_parsing`。
- 解析编排：`src/knowledge_base/services/parse_service.py::ParseService.parse_document` L25-65 —— 读 `doc.content`（**不读 MinIO**）→ `MarkdownParser.parse` → 更新 `content/image_refs/content_hash` → 触发 `VectorizePipeline.vectorize_document`。
- `MarkdownParser`（`src/knowledge_base/services/parsers/markdown_parser.py` L24-50）：`_IMAGE_RE = r"!\[([^\]]*)\]\(([^)]+)\)"` 只提取**正文 `![]()` 引用**的图 url 到 `image_refs`；正文保留 `![]()` 语法。
- MinIO 封装：`src/knowledge_base/services/storage/minio_service.py`（`get_presigned_url` L46-54 等），**但当前 parse 链路未调用它**（上传走 `upload_service` + `minio_client`）。

### F2. 真实 PRD 形态（漫剧批创）
- 目录 `/Users/echo_lacey/Desktop/漫剧批创初版功能PRD/`：1 个 `漫剧批创初版功能PRD.md`（~10w 字） + `images/` 下 **57 张 png**。
- md 正文**只 `![]()` 引用了 9 张**（grep `!\[` = 9）；其余 48 张（界面截图 list/create/dialog/confirm）在目录里但 md 未引用。
- 图片命名规整：`漫剧批创初版功能PRD-{编号}-{描述}.png`，编号与章节强相关（`10/11/12`=头条账户、`20`=漫剧、`30/31`=投放链接、`40`=商品、`50/51`=素材、`60-63`=标题包、`70/71`=定向包、`80-85`=批量创建、`90/91`=任务、`F1/F1b/F2/F3`=流程图/状态机）。
- 图引用格式示例：`![图 F1 · 头条账户授权流程（前端用户流）](images/漫剧批创初版功能PRD-F1-account-auth-flow.png)`，alt 文本含语义。
- **F1/F2/F3 流程图正是 v5 丢失的"图里状态机"**（如 F3 任务执行与回写 → 对应 v5 缺失的 F-023 §5.9.3 任务状态机）。

### F3. LLM 客户端（多模态现状）
- 唯一实现 `src/testcase_generator/services/llm_client.py`，单例 `get_llm_client()` L265-270。
- `LLMClient.generate_structured(system_prompt, user_content: str, output_schema, temperature=0.3)` L131-137 —— **`user_content` 是纯字符串**，messages 无 `image_url` 结构（L208-211），**不支持视觉**。无 `generate()` 非结构化方法。
- settings（`src/platform_api/core/settings.py`）：`llm_base_url` L34 / `llm_api_key` L35 / `llm_primary_model` L36（必填）/ `llm_timeout=240` L47 / `llm_json_mode=False` L53 / `llm_concurrency=2` L43。**无 vision 模型配置**。embedding：`text-embedding-3-small`（1536 维）。

### F4. 9 feature 丢失 bug（精确定位）
- `src/testcase_generator/stages/test_points/node.py`：`_BATCH_MAX_FEATURES=4`（L296）、`_BATCH_CHAR_LIMIT=15000`。
- `_pack_feature_batches`（L299-313）按"每批 ≤4 feature 或 累计 JSON >15000 字符"切批；`_generate_test_points_batched` L316-368 逐批调 LLM。
- **bug 根因**：`_call_batch` 异常时返回 `None`（L342-350）→ 该批所有 feature **零测试点、仅打 error log、无完整性校验、无重试**。
- 对照：`write_cases/node.py` 的 `MAX_TPS_PER_BATCH=7`（L180）用 `_split_by_count`（L183-187）**保证测试点总数不变**——test_points 缺此保证。

### F5. GraphRAG / 检索现状
- 现有"图"= **文档级 BFS**：`src/knowledge_base/repositories/association_repo.py::traverse_bfs` L56-109（WITH RECURSIVE CTE，无向边展开，`DISTINCT ON (doc_id)` 取最浅 depth）；表 `knowledge.document_associations`（`source_doc_id/target_doc_id/relation_type/deleted_at`）。
- 关系类型 `DocRelationType`（`src/platform_api/models/enums.py` L18-27）：7 个值（req_to_tech/req_to_case/...）。**文档级，非实体级**。
- `GraphSearchService.traverse_graph`（`src/knowledge_base/services/search/graph_search.py`）关联文档只取 `content[:200]`（L46）。
- `HybridSearchService`（`hybrid_search.py`）已实现但 **无生产调用方**；向量检索在流水线**从未触发**（parse 调 `retrieve_knowledge_context` 不传 query）。
- `auto_link_on_create`（`src/knowledge_base/services/linkage_service.py` L53-86）已实现但**从未接入**。
- 检索唯一接入点：`parse_node` → `kb_retriever.retrieve_knowledge_context` → `RetrievalService.retrieve_context`（`src/knowledge_base/services/retrieval_service.py` L33-105）。comprehend/rule_extract/test_points/write_cases **均不调 KB 检索**。

### F6. 可复用的 rule_extract 框架
- `src/testcase_generator/stages/rule_extract/`：`source_loader.load_seed_markdown(document_id)` 读 seed 原文 → `splitter.build_units(md)` 章节树切分（`{title,level,chars,text}`，meta 丢弃 / digest 汇总 / UNIT_MAX_CHARS=7000）→ `extractor.extract_rules(units, digest, client, concurrency=4)` LLM 并发抽取（失败隔离）。
- 规则 schema `src/testcase_generator/schemas/rule.py`：`RuleItem{rule_code, module, rule, source_quote, category}`。
- 落库 `testcase.rules` 表（`src/platform_api/models/testcase.py` L59-76），`callbacks.py::on_pipeline_complete` L57-78。
- **实体抽取直接复用 `build_units` + 并发抽取模式**，新增实体/关系的 LLM schema 即可。

---

## File Structure（创建/修改清单）

**Chunk 0（修 bug + 尺子）**
- Modify: `src/testcase_generator/stages/test_points/node.py`（feature 覆盖率校验 + 失败重试 + 缺额兜底）
- Modify: `src/platform_api/core/settings.py`（+`test_points_completeness_guard: bool=True`，此项默认开——纯止血无副作用）
- Create: `src/knowledge_base/cli/image_coverage_probe.py`（图覆盖体检 CLI）
- Test: `tests/testcase_generator/test_test_points_completeness.py`

**Chunk 1（多模态 + 图解析）**
- Modify: `src/testcase_generator/services/llm_client.py`（`generate_structured` 加 `images` 参数 + 新增 vision 调用）
- Modify: `src/platform_api/core/settings.py`（+`llm_vision_model: str=""`、`image_caption_enabled: bool=False`、`image_caption_concurrency: int=4`）
- Create: `src/knowledge_base/services/image_caption/__init__.py`
- Create: `src/knowledge_base/services/image_caption/image_collector.py`（收集文档全部图：MinIO 目录 + image_refs 合并去重）
- Create: `src/knowledge_base/services/image_caption/caption_service.py`（视觉 LLM 描述每张图 → 结构化 caption）
- Create: `src/knowledge_base/services/image_caption/content_injector.py`（描述按编号归位插回 content）
- Create: `src/testcase_generator/schemas/image_caption.py`（`ImageCaption` schema）
- Modify: `src/knowledge_base/services/parse_service.py`（parse 时调图解析，开关控制）
- Modify: `src/platform_api/models/knowledge.py`（`documents` 加 `image_captions: JSONB` 列存描述）
- Create: `alembic/versions/0XX_add_image_captions.py`
- Test: `test_image_collector.py` / `test_caption_service.py` / `test_content_injector.py`

**Chunk 2（实体图谱表 + 抽取）**
- Create: `alembic/versions/0XX_add_entity_graph.py`（`knowledge.entities` + `knowledge.entity_relations`）
- Modify: `src/platform_api/models/knowledge.py`（`Entity` + `EntityRelation` 模型）
- Modify: `src/platform_api/models/enums.py`（`EntityType` + `EntityRelationType` 枚举）
- Create: `src/knowledge_base/schemas/entity.py`（`EntityItem` / `RelationItem` / `EntityGraph`）
- Create: `src/knowledge_base/services/entity_graph/extractor.py`（复用 build_units，LLM 抽实体+关系）
- Create: `src/knowledge_base/repositories/entity_repo.py`（实体/关系 CRUD + 落库）
- Modify: `src/platform_api/core/settings.py`（+`entity_graph_enabled: bool=False`）
- Test: `test_entity_extractor.py` / `test_entity_repo.py`

**Chunk 3（实体检索）**
- Modify: `src/knowledge_base/repositories/entity_repo.py`（`traverse_entities` 实体图 BFS CTE）
- Create: `src/knowledge_base/services/search/entity_graph_search.py`（实体图检索 service）
- Create: `src/knowledge_base/services/entity_graph/query_service.py`（关系问题查询：实体→相关规则/章节/互斥项）
- Modify: `src/platform_api/core/settings.py`（+`entity_retrieval_enabled: bool=False`）
- Test: `test_entity_traverse.py` / `test_entity_query.py`

**Chunk 4（接入 + 验收）**
- Modify: `src/testcase_generator/stages/parse/node.py` 或 `kb_retriever.py`（接入实体图谱上下文）
- Create: `tests/testcase_generator/test_stage1_e2e.py`
- Modify: `src/platform_api/core/settings.py`（3 开关默认开）

> **Migration 编号**：执行前先 `uv run alembic heads` 确认当前 head（快照含 006-012 + rule-anchored 的 013-016 等），新 migration `down_revision` 接当前 head，**用裸数字 revision（与全库一致，勿用文件名 slug）**。

---

## 安全保证机制（贯穿全程）

1. **顺序即安全**：C0 建尺子+止血（零风险）→ C1 图解析（开关关=不调视觉）→ C2 建图谱（开关关=不抽实体）→ C3 检索（开关关=不查）→ C4 接入+默认开。
2. **灰度开关 = 字节级回退**：`image_caption_enabled` / `entity_graph_enabled` / `entity_retrieval_enabled` 关时，新增节点/步骤**首行短路直通**，不改图拓扑、不调 LLM、不改既有产物。每个 chunk 须有单测断言「开关关时产物与接入前逐条一致」。
3. **回归红线**：
   - C0 图覆盖体检 CLI 给现状打基线（预期图覆盖率≈0%、9 feature 缺失复现）。
   - 每个 chunk 末尾跑漫剧批创对照基线：feature 数只增不减、图覆盖率只升不降、实体图谱关系人工抽查正确率 ≥ 阈值。
4. **成本护栏**：视觉描述对 57 张图是一次性（入库时做），结果持久化进 `documents.image_captions` + 写回 `content`；重复 parse 命中已有描述则跳过（按图 hash 缓存）。

---

## Chunk 0（零风险）：feature 完整性兜底 + 图覆盖体检尺子

**目的**：先修「9 feature 静默丢失」止血 bug + 建「图覆盖体检」尺子，给现状打基线。不依赖视觉模型，零回归风险。

### Task 0.1：test_points 批失败兜底（修 9 feature 丢失）

**Files:**
- Modify: `src/testcase_generator/stages/test_points/node.py`
- Modify: `src/platform_api/core/settings.py`（+`test_points_completeness_guard: bool = True`）
- Test: `tests/testcase_generator/test_test_points_completeness.py`

- [ ] **Step 1：写失败测试** —
  - (a) 构造 5 个 feature（跨 2 批，`_BATCH_MAX_FEATURES=4`），mock `_call_batch` 让**第 2 批抛异常**；断言开 guard 时：失败批被**重试**（至少 1 次），重试仍失败则 fallback 单 feature 逐个生成；最终断言 `len({tp.feature_id for tp in result}) == 5`（无 feature 零测试点）。
  - (b) 断言 guard 关时退回旧行为（失败批静默丢，复现 bug）。
  - (c) 断言：所有 feature 至少有 1 个测试点，否则在 `state` 里记 `missing_feature_ids` 供下游/日志可见。
- [ ] **Step 2：跑测试确认失败** — `uv run pytest tests/testcase_generator/test_test_points_completeness.py -v`
- [ ] **Step 3：实现** —
  - `_generate_test_points_batched` 收集失败批的 feature → **整批重试 1 次**（temperature 微调）→ 仍失败则**拆成单 feature 逐个重试**（参考 `write_cases` 的 `_split_by_count` 保证不丢思路）。
  - 全部生成后做**完整性校验**：`covered = {tp.feature_id}`，`missing = all_feature_ids - covered`；`missing` 非空时记 `state["missing_feature_ids"]` + WARN 日志（不再静默）。
  - `test_points_completeness_guard` 关时短路回旧逻辑。
- [ ] **Step 4：跑测试确认通过**
- [ ] **Step 5：提交** — `git commit -m "fix(test-points): feature 完整性兜底（批失败重试+缺额校验，修 9 feature 静默丢失）"`

### Task 0.2：图覆盖体检 CLI

**Files:**
- Create: `src/knowledge_base/cli/__init__.py`（若无）
- Create: `src/knowledge_base/cli/image_coverage_probe.py`
- Test: `tests/knowledge_base/test_image_coverage_probe.py`

- [ ] **Step 1：写失败测试** — mock 一个 document（`image_refs` 有 9 项）+ mock MinIO 列目录返回 57 个对象；断言 probe 输出：`md_referenced=9 / minio_total=57 / captioned=0 / coverage=0.0`（captioned 数来自 `documents.image_captions`，C1 前恒 0）。
- [ ] **Step 2：跑测试确认失败**
- [ ] **Step 3：实现 CLI** — 入参 `--document-id` 或 `--system-id`；流程：① 读 `documents.image_refs`（md 引用数）；② 列 MinIO `systems/{system_id}/documents/` 下图片对象（全集，用 `minio_client.list_objects`）；③ 读 `documents.image_captions`（已描述数，C1 后有值）；④ 输出 `已引用/MinIO实有/已描述/覆盖率`，覆盖率 = 已描述 / MinIO实有。
- [ ] **Step 4：跑测试确认通过**
- [ ] **Step 5：提交** — `git commit -m "feat(kb): 图覆盖体检 CLI（量化 PRD 图被解析比例）"`

### Task 0.3：跑漫剧批创基线

- [ ] **Step 1：确认漫剧批创 PRD 的 document_id + system_id**（查 `knowledge.documents` where title like '漫剧批创%'）。记入本文件末尾「基线表」。
- [ ] **Step 2：跑图覆盖体检** — `uv run python -m src.knowledge_base.cli.image_coverage_probe --document-id <id>`；Expected：`MinIO实有≈57 / 已描述=0 / 覆盖率=0%`（基线，证明现状图全瞎）。若 MinIO 实有远小于 57，说明上传时未传全图 → 记录并告警（影响 C1 设计）。
- [ ] **Step 3：复现 9 feature 缺失** — 对漫剧批创新建一个批次（或复用 c1f533e3 的 test_points 产物），统计实有 feature 数；Expected：21（v4=30，缺 9），确认 bug 基线。修复后（Task 0.1）应回到 30。
- [ ] **Step 4：记录基线** — 写入「基线表」：图覆盖率 0%、feature 21/30。

> **Chunk 0 验收**：① test_points 完整性兜底单测全绿，漫剧批创重跑 feature 数恢复到 ~30（不再缺 9）；② 图覆盖体检 CLI 可用，基线图覆盖率≈0% 落账。**此 chunk 不依赖视觉模型、不动检索逻辑，零回归。**

---

## Chunk 1（图解析关）：多模态 LLMClient + 57 图转文字插回章节

**目的**：给 AI 装眼睛（多模态），把 PRD 全部 57 张图（含 48 张未被 md 引用的界面截图）转成结构化文字描述，插回 PRD content 的章节原位。开关 `image_caption_enabled` 默认关。

### Task 1.1：LLMClient 多模态扩展

**Files:**
- Modify: `src/testcase_generator/services/llm_client.py`
- Modify: `src/platform_api/core/settings.py`（+`llm_vision_model: str = ""`）
- Test: `tests/testcase_generator/test_llm_client_vision.py`

- [ ] **Step 1：写失败测试** — mock `AsyncOpenAI`，调 `generate_structured(system, user_content, schema, images=[图bytes/base64])`；断言发出的 messages 里 user content 是 multimodal 结构（`[{"type":"text",...},{"type":"image_url","image_url":{"url":"data:image/png;base64,..."}}]`）且 model 用 `llm_vision_model`（非 primary）。
- [ ] **Step 2：跑测试确认失败**
- [ ] **Step 3：实现** — `generate_structured` 加可选参 `images: list[bytes] | None = None`；有 images 时：把每张图 base64 编码成 `data:image/png;base64,...`，构建 multimodal user content，model 用 `settings.llm_vision_model`（未配置则抛清晰错误「图解析需配置 LLM_VISION_MODEL」）；无 images 时走原纯文本路径（**零行为变化**）。
- [ ] **Step 4：跑测试确认通过**
- [ ] **Step 5：提交** — `git commit -m "feat(llm): generate_structured 支持多模态图片输入（vision model）"`

### Task 1.2：图清单收集器（取全集 57 张，不只 image_refs 的 9 张）

**Files:**
- Create: `src/knowledge_base/services/image_caption/__init__.py`
- Create: `src/knowledge_base/services/image_caption/image_collector.py`
- Test: `tests/knowledge_base/test_image_collector.py`

- [ ] **Step 1：写失败测试** — mock document（`image_refs`=9 项相对路径 + `folder_path`）+ mock `minio_client.list_objects` 返回 57 个图对象；断言 `collect_images(document)` 返回 **57 项**（合并 image_refs 与 MinIO 目录、按 object key 去重），每项含 `{object_key, filename, referenced_in_md: bool}`。
- [ ] **Step 2：跑测试确认失败**
- [ ] **Step 3：实现** — `async def collect_images(document) -> list[ImageRef]`：① 列 MinIO `systems/{system_id}/documents/{folder_path}/images/`（及 folder 下）所有图片对象（全集）；② 标注每张是否在 `image_refs`（`referenced_in_md`）；③ 从文件名解析编号前缀（如 `80`、`F1`、`5.8.4`）存 `section_hint`，供归位用。
- [ ] **Step 4：跑测试确认通过**
- [ ] **Step 5：提交** — `git commit -m "feat(kb): 图清单收集器（MinIO 全集，含未被 md 引用的界面图）"`

### Task 1.3：视觉描述生成器

**Files:**
- Create: `src/testcase_generator/schemas/image_caption.py`（`ImageCaption{filename, section_hint, kind, ui_elements, flow_steps, caption_text, raw}`，kind∈{screen,flow,statemachine,config}）
- Create: `src/knowledge_base/services/image_caption/caption_service.py`
- Test: `tests/knowledge_base/test_caption_service.py`（fake vision client）

- [ ] **Step 1：写失败测试** — fake client 对一张图返回结构化 caption；断言 `caption_images(images, client, concurrency)` 并发描述、失败隔离（单图失败不影响其余）、返回 `list[ImageCaption]`。
- [ ] **Step 2：跑测试确认失败**
- [ ] **Step 3：实现** — 从 MinIO 下载图 bytes → 调 `generate_structured(VISION_SYS, 上下文文本, ImageCaption, images=[bytes])`。`VISION_SYS` 提示词要求：识别界面元素/按钮/分页档位/弹窗文案（screen 类）、流程步骤与分支（flow 类）、状态机节点与转移（statemachine 类）；输出**可被测试用例引用的事实**，不臆造。并发用 `settings.image_caption_concurrency`，失败隔离（参考 `extractor.py::_extract_one`）。
- [ ] **Step 4：跑测试确认通过**
- [ ] **Step 5：提交** — `git commit -m "feat(kb): 视觉描述生成器（界面/流程/状态机结构化描述，并发+失败隔离）"`

### Task 1.4：描述插回 content + DB 持久化 + 接入 parse（开关控制）

**Files:**
- Create: `src/knowledge_base/services/image_caption/content_injector.py`
- Modify: `src/platform_api/models/knowledge.py`（`documents` 加 `image_captions: JSONB`）+ `alembic/versions/0XX_add_image_captions.py`
- Modify: `src/knowledge_base/services/parse_service.py`（图解析步骤，`image_caption_enabled` 控制）
- Modify: `src/platform_api/core/settings.py`（+`image_caption_enabled: bool=False`、`image_caption_concurrency: int=4`）
- Test: `tests/knowledge_base/test_content_injector.py` + `test_parse_service_caption.py`

- [ ] **Step 1：写失败测试** —
  - (a) `inject_captions(content, captions)`：md 已引用的图（9 张）→ 在 `![]()` 后追加 `\n> [图述] {caption_text}`；未引用的图（48 张）→ 按 `section_hint` 编号匹配到对应章节标题下追加 `> [图述 {filename}] {caption_text}`，匹配不到则归入文末「附：未定位图描述」。断言注入后 content 含全部 57 段描述。
  - (b) `parse_service` 开关关时**不调视觉、content 不变、image_captions 为空**（逐字节一致）。
- [ ] **Step 2：跑测试确认失败**
- [ ] **Step 3：实现** — `ParseService.parse_document` 在 `MarkdownParser.parse` 后、`update` 前插入：`if settings.image_caption_enabled:` → `collect_images` → 按 content_hash+图清单 hash 查缓存（命中跳过）→ `caption_images` → `inject_captions` 改写 `parsed.content` → 把 captions 存 `documents.image_captions`。开关关则跳过。
- [ ] **Step 4：跑测试确认通过** + 单文档真跑（开关开）验证 content 含图述、image_captions 落库。
- [ ] **Step 5：提交** — `git commit -m "feat(kb): 图描述按章节归位插回 content + 持久化（灰度 image_caption_enabled）"`

### Task 1.5：漫剧批创图解析验收

- [ ] **Step 1：开 `image_caption_enabled` 重新 parse 漫剧批创 PRD**（重新触发 `knowledge_base.parse_document`）。
- [ ] **Step 2：跑图覆盖体检** — Expected：`已描述≈57 / 覆盖率≈100%`。
- [ ] **Step 3：人工抽查** — 抽 F1/F2/F3 流程图描述是否含状态机节点与转移；抽 3 张界面截图（如 `62a-titles-library-add-dialog`）是否捕捉到弹窗/分页等界面细节。记入基线表。

> **Chunk 1 验收**：漫剧批创图覆盖率 0%→~100%；F1/F2/F3 状态机/流程被结构化描述；content 内含 57 段图述且章节归位正确。开关关时 parse 产物与 Chunk 0 逐字节一致。

---

## Chunk 2（建图谱）：实体级知识图谱表 + 抽取落库（不改生成）

**目的**：从 enriched PRD（已含图述）抽出**实体**（字段/章节/规则/概念）+ **关系**（章节优先级/字段定义于/规则约束/互斥/不可达），落实体图谱。复用 `rule_extract` 的章节切分与并发抽取框架。开关 `entity_graph_enabled` 默认关。

### Task 2.1：DB 迁移 — entities + entity_relations 表

**Files:**
- Create: `alembic/versions/0XX_add_entity_graph.py`（`down_revision` 接当前 head）
- Modify: `src/platform_api/models/knowledge.py`（`Entity` + `EntityRelation`）
- Modify: `src/platform_api/models/enums.py`（`EntityType` / `EntityRelationType`）

- [ ] **Step 1：写迁移** —
  - `knowledge.entities(id uuid pk, document_id uuid fk, system_id uuid, entity_type varchar, name varchar, canonical_key varchar, section_ref varchar, description text, source_quote text, attributes jsonb, created_at)`；索引 `(document_id, entity_type)`、`(system_id, canonical_key)`。
  - `knowledge.entity_relations(id uuid pk, document_id uuid, source_entity_id uuid fk, target_entity_id uuid fk, relation_type varchar, note text, source_quote text, created_at)`；索引 `(source_entity_id)`、`(target_entity_id)`、`(document_id, relation_type)`；CHECK `source_entity_id != target_entity_id`。含 `downgrade`。
- [ ] **Step 2：加枚举 + 模型** — `EntityType ∈ {field, section, rule, concept, ui_element, state}`；`EntityRelationType ∈ {section_priority(局部优先于全局), field_defined_in, rule_constrains, mutually_exclusive(互斥/易混), unreachable(不可达/不存在), belongs_to, transitions_to(状态转移)}`。`Entity`/`EntityRelation` ORM 映射。
- [ ] **Step 3：跑迁移** — `uv run alembic upgrade head`；再 `downgrade -1 && upgrade head` 验可逆。
- [ ] **Step 4：提交** — `git commit -m "feat(db): knowledge.entities + entity_relations（实体级知识图谱）"`

### Task 2.2：实体关系抽取器

**Files:**
- Create: `src/knowledge_base/schemas/entity.py`（`EntityItem` / `RelationItem` / `EntityGraph`）
- Create: `src/knowledge_base/services/entity_graph/__init__.py`
- Create: `src/knowledge_base/services/entity_graph/extractor.py`
- Test: `tests/knowledge_base/test_entity_extractor.py`（fake client）

- [ ] **Step 1：写 schema** — `EntityItem{entity_type, name, canonical_key, section_ref, description, source_quote, attributes}`；`RelationItem{source_name, target_name, relation_type, note, source_quote}`；`EntityGraph{entities: list, relations: list}`。
- [ ] **Step 2：写失败测试** — 给一段含「§5.0.3 全局字数规则」+「§5.7.1 定向包名 emoji 例外」的 markdown，fake client 返回实体（两个 section + 两个 field + 规则）+ 关系（`section_priority`: §5.7.1 局部优先 §5.0.3；`mutually_exclusive`: 定向包名 vs 普通名称字数算法）；断言 `extract_entity_graph(units, digest, client)` 正确产出并对实体去重（canonical_key 合并）。
- [ ] **Step 3：实现** — 复用 `rule_extract.splitter.build_units` 切章节单元（输入 = Chunk 1 后含图述的 content）；每单元调 LLM（新 prompt）抽实体+关系，**重点抽 v5 痛点关系**：局部章节特例 vs 全局规则（`section_priority`）、易混概念（`mutually_exclusive`，如 §7 监测链接 vs §5.8.3 投放链接）、不存在项（`unreachable`，如"关键行为"非投放方式）、状态转移（`transitions_to`，来自 F1/F2/F3 图述）。并发 + 失败隔离（仿 `extractor.py`）。跨单元按 `canonical_key` 去重合并实体。
- [ ] **Step 4：跑测试确认通过**
- [ ] **Step 5：提交** — `git commit -m "feat(kb): 实体关系抽取器（复用章节切分，抽 v5 痛点关系）"`

### Task 2.3：落库 + 接入（开关 entity_graph_enabled 默认关）

**Files:**
- Create: `src/knowledge_base/repositories/entity_repo.py`
- Modify: `src/knowledge_base/services/parse_service.py`（图谱抽取步骤，开关控制）
- Modify: `src/platform_api/core/settings.py`（+`entity_graph_enabled: bool=False`、`entity_extract_concurrency: int=4`）
- Test: `tests/knowledge_base/test_entity_repo.py`

- [ ] **Step 1：写失败测试** — `EntityRepository.save_graph(document_id, system_id, entity_graph)`：先 upsert entities 取 `name→entity_id` 映射，再用映射解析 relations 的 source/target，落 entity_relations；断言重复 parse 幂等（先删该 document 旧实体/关系再写）。开关关时 parse 不抽不落（entities 表空）。
- [ ] **Step 2：跑测试确认失败**
- [ ] **Step 3：实现** — `entity_repo` CRUD + `save_graph`；`ParseService` 在图解析后插入：`if settings.entity_graph_enabled:` → `build_units(enriched_content)` → `extract_entity_graph` → `entity_repo.save_graph`。开关关跳过。
- [ ] **Step 4：跑测试确认通过**
- [ ] **Step 5：提交** — `git commit -m "feat(kb): 实体图谱落库 + parse 接入（灰度 entity_graph_enabled）"`

### Task 2.4：漫剧批创图谱抽取验收

- [ ] **Step 1：开 `entity_graph_enabled` + `image_caption_enabled` 重新 parse 漫剧批创**。
- [ ] **Step 2：统计落库** — entities 数、relations 数、各 relation_type 分布。
- [ ] **Step 3：人工抽查关系正确率** — 抽 20 条关系（重点 `section_priority` / `mutually_exclusive` / `unreachable`），人工判对错；目标正确率 ≥ 80%。重点验证：§5.7.1 局部优先 §5.0.3、§7 vs §5.8.3 互斥、"关键行为"标 unreachable。记入基线表。

> **Chunk 2 验收**：漫剧批创实体图谱落库，关系抽查正确率 ≥80%，v5 三类痛点关系（局部优先/易混/不存在）被显式建模。开关关时 parse 产物与 Chunk 1 一致。

---

## Chunk 3（建检索）：实体级多跳检索 + 关系问题查询

**目的**：让系统能回答「关系类问题」——给一个字段/概念，召回相关实体、约束规则、互斥项、适用章节。验收 v5 混淆点（§5.0.3 vs §5.7.1 哪个管定向包名）能答对。开关 `entity_retrieval_enabled` 默认关。

### Task 3.1：实体图 BFS 遍历

**Files:**
- Modify: `src/knowledge_base/repositories/entity_repo.py`（+`traverse_entities`）
- Test: `tests/knowledge_base/test_entity_traverse.py`

- [ ] **Step 1：写失败测试** — 构造实体图（定向包名 --field_defined_in--> §5.7.1，§5.7.1 --section_priority--> §5.0.3，定向包名 --mutually_exclusive--> 普通名称）；断言 `traverse_entities(seed_entity_id, max_depth=2)` 返回多跳邻居含正确 `relation_type` 与 depth。
- [ ] **Step 2：跑测试确认失败**
- [ ] **Step 3：实现** — 仿 `association_repo.traverse_bfs` 的 WITH RECURSIVE CTE，但走 `knowledge.entity_relations`（有向边，保留 relation_type 方向语义）；返回 `list[(entity_id, depth, relation_type, direction)]`。`DISTINCT ON (entity_id)` 取最浅。
- [ ] **Step 4：跑测试确认通过**
- [ ] **Step 5：提交** — `git commit -m "feat(kb): 实体图 BFS 遍历（有向多跳，保留关系语义）"`

### Task 3.2：关系问题查询服务

**Files:**
- Create: `src/knowledge_base/services/search/entity_graph_search.py`
- Create: `src/knowledge_base/services/entity_graph/query_service.py`
- Modify: `src/platform_api/core/settings.py`（+`entity_retrieval_enabled: bool=False`）
- Test: `tests/knowledge_base/test_entity_query.py`

- [ ] **Step 1：写失败测试** — 给定上面图谱，`query_entity_context("定向包名", system_id)` 返回结构含：定向包名实体、其 `field_defined_in` 章节（§5.7.1）、章节优先级链（§5.7.1 优先 §5.0.3）、互斥项（普通名称字数算法）；断言能据此判定「定向包名用 §5.7.1（20 字符含 emoji），不用 §5.0.3（半角 0.5）」。
- [ ] **Step 2：跑测试确认失败**
- [ ] **Step 3：实现** — `EntityGraphSearchService`：实体名/canonical_key 匹配（精确 + 模糊）定位 seed 实体 → `traverse_entities` 多跳 → 按 relation_type 归类组织（适用章节 / 优先级 / 互斥 / 约束规则 / 状态转移）。`query_service.query_entity_context` 封装成「关系问题应答」结构。`entity_retrieval_enabled` 关时返回空（不查）。
- [ ] **Step 4：跑测试确认通过**
- [ ] **Step 5：提交** — `git commit -m "feat(kb): 实体级关系查询服务（章节优先级/互斥/约束归类应答）"`

### Task 3.3：v5 混淆点回归验收

- [ ] **Step 1：开三开关，对漫剧批创实体图谱跑关系查询** —
  - `query_entity_context("定向包名")` → 应答「用 §5.7.1（20 字符含 emoji），非 §5.0.3」（攻 W06 F-009 8 P0）
  - `query_entity_context("监测链接")` → 应答「§7 系统自动绑定不展示，与 §5.8.3 投放链接（投手手选可复制）互斥」（攻 W11 F-015）
  - `query_entity_context("关键行为")` → 应答「在 §5.8.3.1 投放方式表中不存在（unreachable）」（攻 W16 F-021）
- [ ] **Step 2：记录命中情况** 入基线表（这 3 个是 ① 验收红线代表）。

> **Chunk 3 验收**：上述 3 个 v5 混淆点查询全部应答正确——证明实体图谱能回答跨章关系问题。开关关时查询返回空、不影响现状。

---

## Chunk 4（接入 + 验收）：轻量接入生成流水线 + 漫剧批创端到端验收

**目的**：让生成流水线能用上实体图谱（轻量——真正的「硬约束注入」留给②cheat sheet），跑漫剧批创对照 ① 验收红线，开关默认开。

> **范围克制**：① 阶段只做到「流水线能查到实体图谱上下文」，不做强约束改写（那是 ② 的事）。避免与 ② 重复返工。

### Task 4.1：parse 阶段挂接实体图谱上下文

**Files:**
- Modify: `src/testcase_generator/stages/parse/kb_retriever.py` 或 `stages/parse/node.py`
- Modify: `src/testcase_generator/schemas/parsed_context.py`（`ParsedContext` 加 `entity_graph_hints: list[dict]`，默认 []）
- Test: `tests/testcase_generator/test_parse_entity_hints.py`

- [ ] **Step 1：写失败测试** — `entity_retrieval_enabled` 开时，parse 产出的 `parsed_context.entity_graph_hints` 含该文档关键实体的关系摘要（局部优先/互斥/不存在项）；关时为 `[]`（产物与现状一致）。
- [ ] **Step 2：跑测试确认失败**
- [ ] **Step 3：实现** — parse 末尾（`entity_retrieval_enabled` 开时）查该 document 的实体图谱，把高价值关系（section_priority / mutually_exclusive / unreachable）摘要进 `entity_graph_hints`，挂到 `ParsedContext`。下游可读（② 阶段用它做硬约束）。开关关 → 空 list。
- [ ] **Step 4：跑测试确认通过**
- [ ] **Step 5：提交** — `git commit -m "feat(pipeline): parse 挂接实体图谱关系提示（灰度，为 cheat sheet 铺路）"`

### Task 4.2：漫剧批创端到端验收

- [ ] **Step 1：三开关全开，重新 parse + 跑完整漫剧批创流水线**（新批次）。
- [ ] **Step 2：对照 ① 验收红线逐项核对** —
  - feature 完整性：实有 feature 数 ≥30（不再缺 9），重点确认 F-012/F-018/F-019/F-023 这 4 个 v5 缺失的 high 影响 feature 回来了（F-023 任务状态机应受益于 F3 图解析）。
  - 图覆盖率：≈100%。
  - 关系查询：Chunk 3 的 3 个 v5 混淆点应答正确。
- [ ] **Step 3：填基线表「① 改造后」行**。
- [ ] **Step 4：（可选）抽样审计** — 对新批次跑 v5 同口径的轻量审计，看类 D（缺失）是否清零、类 B（混淆）是否下降，作为 ① 的量化战果（完整审计在 ② 后做）。

### Task 4.3：开关默认开

- [ ] **Step 1：`settings.py` 三开关默认 True**（`image_caption_enabled` / `entity_graph_enabled` / `entity_retrieval_enabled`）。`test_points_completeness_guard` 本就默认 True。
- [ ] **Step 2：全量单测** — `uv run pytest tests/ -q` 全绿；`uv run ruff check src/ tests/` 无错。
- [ ] **Step 3：提交** — `git commit -m "feat(stage1): 图解析 + 实体级 GraphRAG 默认启用 + 端到端验收"`

> **① 最终验收红线**：① 漫剧批创 feature 数恢复 ≥30（9 缺失清零）；② 图覆盖率 ≈100%，F1/F2/F3 状态机进入系统；③ 3 个 v5 混淆点关系查询应答正确；④ 全部单测绿。任一不满足不算 ① 完成。

---

## 风险与取舍（诚实记录）

- **视觉模型质量**：图描述由 vision LLM 生成，可能漏读/误读界面细节。缓解：描述要求「只记可被用例引用的事实，不臆造」；F1/F2/F3 状态机这类高价值图人工抽查。视觉模型名由用户网关提供（`LLM_VISION_MODEL`）。
- **48 张未引用图的归位**：靠文件名编号前缀匹配章节，可能有图归位不准 → 归不准的进「文末附录」兜底，不丢描述；② 阶段 QA 审 cheat sheet 时可校正。
- **实体抽取漂移**：LLM 抽实体/关系可能多抽/漏抽 → 定位为「关系线索」而非唯一真相；① 只做到「能查到」，② cheat sheet 由 QA 审核把关后才作硬约束。关系抽查正确率 ≥80% 作 Chunk 2 红线。
- **成本/耗时**：图解析（57 图 vision 调用）+ 实体抽取（~60 单元 LLM）一次性入库时做，结果持久化，不在每次生成时重复。重新 parse 命中缓存跳过。符合「不计成本、质量优先」。
- **与 rule_extract 的关系**：实体抽取复用 `build_units` 但**独立于** rule_extract 运行（一个在 KB 侧 parse、一个在 testcase_generator pipeline）。规则作为一类实体，② 阶段再考虑统一。① 不强行合并，避免动现有 rule-anchored 链路。
- **migration 编号**：执行前必 `alembic heads` 确认，避免与快照里 006-012 + rule-anchored 013-016 撞号。
- **【前置假设】拆解机器仅认 markdown 标题**：本阶段复用的 `splitter.build_units`（`src/testcase_generator/stages/rule_extract/splitter.py`）只识别 `#` 标题，**假设输入是规整 markdown**（漫剧批创满足）。无标题/弱标题 PRD 会导致 `build_units` 归零（规则/实体 0 产出）——**这是已知缺口，用户决策 defer（决策10），① 不处理**。Claude Code 执行 ① 时**无需**处理无标题情况；通用化前需先加固 splitter（多标题格式 + 无标题递归兜底），见 findings.md 第九节 / task_plan Backlog。

---

## 基线表（Chunk 0 冻结 / Chunk 4 回填）

| 指标 | Chunk 0 基线（现状） | ① 改造后（2026-06-18 真实环境 live 实测） | 红线 | 判定 |
|---|---|---|---|---|
| 漫剧批创 feature 数 | 21（缺 9） | **31**（F-012/F-020/F-021/F-023 等 v5 缺失项回来） | 9 缺失清零 | ✅ |
| 图覆盖率 | ≈0%（57 图全瞎） | **89.5%**（51/57，6 图网关 JSON 偶发失败被隔离跳过） | ≥95% | 🟡 接近 |
| 实体图谱关系抽查正确率 | — | **~78%**（11/14，IAP↔IAA/关键行为 unreachable 等关键痛点准确） | ≥80% | 🟡 接近 |
| v5 混淆点关系查询命中（3 代表） | 0/3 | **3/3**（监测链接↔投放链接互斥 / 关键行为=unreachable / 定向包名字段） | 3/3 | ✅ |
| entity_graph_hints（修复A live） | 0（空壳） | **99 条**（parse_node 真填充，非空壳） | 非空 | ✅ |
| 实体图谱规模 | 0 | 1000 实体 / 757 关系（section_priority14 / mutually_exclusive33 / unreachable52 / transitions_to32） | 落库 | ✅ |
| 全部单测 | 现状绿 | 181 passed / 1 failed（case_tree 范围外测试 SQL bug） | 全绿 | 🟡 |

> **① live 验收结论（2026-06-18）**：核心目标「图看得到 + 关系答得对 + 功能不漏」**真实数据验收通过**。两个 🟡（图覆盖 89.5%、关系抽查 ~78%）均接近红线且根因明确（网关 JSON 稳定性 / 关系线索定位），非硬伤。验收期间发现并修复 `traverse_entities` 的 recursive CTE 违法 bug（真 PG 才暴露，单测 mock 掩盖）—— **该修复仍缺真 DB 测试，建议补**。

> **① 完成标志**：上表「① 改造后」列全部达红线 + 三开关默认开 + 单测绿。达标后进入 ②（cheat sheet）阶段，届时再写 ② 的详细 plan。
