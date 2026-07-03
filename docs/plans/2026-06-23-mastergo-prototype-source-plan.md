# 落点⑦ MasterGo 原型规格接入 — 实施计划 v2（一次性存量迁移工具）

> **For agentic workers:** REQUIRED: 用 superpowers:executing-plans 执行；步骤用 `- [ ]` 勾选。

**Goal:** 把存量 PRD 里 MasterGo 原型链接（**多为只带 page_id**）背后的结构化规格（字段/控件/状态机/权限）抽出来，幂等回灌进 `knowledge.documents.content`，让后续生成"看得见"这些原本只在原型里的规格——根治存量"薄 PRD"。一次性跑、不进生成热路径。

**Architecture（已端到端实测验证，见 design §7）：**
```
扫 documents.content 含 mastergo.com 的老 PRD
  → extract 链接（page_id / layer_id / goto）
  → page_id：无头浏览器读图层面板 DOM 枚举顶层 frame layer_id
     layer_id：直接用
  → getDsl 每帧 → dsl_to_spec_digest → 过滤 MasterGo 广告帧
  → 幂等注入 content（哨兵标记）+ 重算 content_hash + 重嵌（VectorizePipeline）
```
登录态：一次性 headed 登录 → 持久化 `.mastergo_session`（gitignore），之后无头复用。默认 `--dry-run` 不写库。

**Tech Stack:** Python 3.12, asyncio, httpx, **playwright（仓库现成依赖，已验证无头复用会话）**, SQLAlchemy, pytest。

> 设计依据：`docs/spec/2026-06-23-mastergo-prototype-source-design.md`（§7 为本计划依据）。

---

## 现状速查（已验证可复用）

- `src/testcase_generator/stages/parse/mastergo_fetch.py`：`extract_mastergo_links`（已识别 page_id/layer_id/`is_page_only`）、`extract_goto_links`/`resolve_goto`、`fetch_dsl`（头 `X-MG-UserAccessToken`，实测通）、`dsl_to_spec_digest`（实测 6809 字规格）。**纯函数全复用，不重写。**
- `knowledge.documents`：`content`(Text，markdown，parse 的输入)、`content_hash`、`embedding_status`。回灌目标就是 `content`。
- `DocumentRepository.update(doc_id, content=, content_hash=)`；`hashlib.sha256(content.encode()).hexdigest()`（与 `parse_service.py:150` 一致）；`VectorizePipeline(session).vectorize_document(doc_id)` 重嵌。
- `scripts/` 已存在（`e2e_verify.py` 等）；DB 会话工厂 `src.knowledge_base.db.async_session_factory`。
- 探针实测：`page_id=68:91864` → 枚举 7 顶层帧（`90:420043` 等），其中 2 帧是 MasterGo 广告稿（"MasterGo MCP / Editorial Architecture / 赋予 AI 掌控画布"）需过滤。
- 验证素材：自签书（**含** page_id 链接，§6.2）；漫剧/其他无链接 PRD（零回归基准）。
- **不动生成热路径**：`parse/node.py` 里现有的 `enrich_sections_with_mastergo` 调用保持灰度关（`mastergo_enabled=False`），本期不依赖、不修改其行为。

## File Structure

- **Create** `scripts/mastergo_backfill.py`：CLI（`login` / `scan` / `run`），含浏览器枚帧器 + 编排 + 噪音过滤 + DB 回灌。
- **Modify** `src/testcase_generator/stages/parse/mastergo_fetch.py`：新增纯函数 `filter_promo_digests` / `build_backfill_block` / `inject_backfill_block`（幂等注入），供 CLI 与单测复用。
- **Create** `tests/testcase_generator/test_mastergo_backfill.py`：噪音过滤 + 幂等注入 + resolve（mock 浏览器+mock fetch_dsl）单测。
- **Modify** `.gitignore`：加 `.mastergo_session/`、`.qa_probe/`（若未忽略）。
- `.env`：`MASTERGO_API_TOKEN=`（已有约定，不提交）。

---

## Chunk 1: 可复用纯函数（TDD）

### Task 1: 噪音过滤 + 幂等注入（写进 `mastergo_fetch.py`）

- [ ] **Step 1: 写测试（先失败）** `tests/testcase_generator/test_mastergo_backfill.py`
```python
from src.testcase_generator.stages.parse.mastergo_fetch import (
    filter_promo_digests, build_backfill_block, inject_backfill_block, BACKFILL_SENTINEL,
)

def test_filter_promo():
    items = [("审核记录", "审核状态 / 待提审 / 审核通过"),
             ("editorial-artboard", "MasterGo MCP / 赋予 AI 掌控画布的原生能力 / access key")]
    kept = filter_promo_digests(items)
    assert len(kept) == 1 and kept[0][0] == "审核记录"

def test_inject_idempotent():
    base = "# PRD\n正文……\n见原型 https://mastergo.com/file/1?page_id=2"
    block = build_backfill_block({"https://mastergo.com/file/1?page_id=2": "· 列表：字段A / 字段B"})
    once = inject_backfill_block(base, block)
    twice = inject_backfill_block(once, build_backfill_block({"https://mastergo.com/file/1?page_id=2": "· 列表：字段A / 字段B / 字段C"}))
    assert once.count(BACKFILL_SENTINEL) == 1
    assert twice.count(BACKFILL_SENTINEL) == 1           # 不重复
    assert "字段C" in twice and base.split("见原型")[0] in twice  # 替换为最新、原文保留
```
Run → FAIL。

- [ ] **Step 2: 实现**（追加到 `mastergo_fetch.py`）
  - `BACKFILL_SENTINEL = "<!-- MASTERGO_SPEC_BACKFILL v1 -->"`、结束哨兵 `<!-- /MASTERGO_SPEC_BACKFILL -->`。
  - `_PROMO_MARKERS = ("MasterGo MCP", "Editorial Architecture", "赋予 AI 掌控画布", "MCP 服务", "access key", "editorial-artboard")`。
  - `filter_promo_digests(items: list[tuple[str,str]]) -> list[tuple[str,str]]`：丢弃 命中 ≥2 个 marker 或 name 以 `editorial-artboard` 开头 的帧。
  - `build_backfill_block(url_to_digest: dict[str,str]) -> str`：哨兵包裹的 markdown，标题 `## 原型规格补全（MasterGo 设计稿自动抽取）`，按 url 分组列出 digest。
  - `inject_backfill_block(content, block) -> str`：含哨兵→正则整块替换；否则末尾追加。
- [ ] **Step 3**：`uv run pytest tests/testcase_generator/test_mastergo_backfill.py -q` → 纯函数测试过。

---

## Chunk 2: 浏览器枚帧器 + 编排

### Task 2: `scripts/mastergo_backfill.py` 枚帧器（实测逻辑固化）

- [ ] **Step 1**：实现 `async harvest_frame_ids(file_id, page_id, session_dir, headless=True) -> list[str]`
  - `launch_persistent_context(user_data_dir=session_dir, headless=headless, viewport=1680x1000)`。
  - `goto https://mastergo.com/file/{file_id}?page_id={quote(page_id)}`，等 `[nodename]` 出现。
  - 登录态校验：body 含 `获取验证码/注册登录后查看` → raise `MgNotLoggedIn`（提示先跑 `login`）。
  - `page.evaluate(JS_COLLECT)`：滚动图层面板容器，收集 `[data-id]` 且 `data-offsetleft=="0"`、`data-id` 形如 `\d+:\d+` 的去重列表（JS 同探针 `.qa_probe/mastergo_enum.py`，已验证）。
  - 返回顶层 frame layer_id 列表；异常返回 `[]` 并记 warning（不阻断整批）。

- [ ] **Step 2**：实现 `async resolve_specs(content, token, session_dir) -> dict[str,str]`（url → digest）
  - `refs = extract_mastergo_links(content)` + `resolve_goto(extract_goto_links(content))`。
  - 每个 ref：
    - `is_page_only` → `ids = await harvest_frame_ids(ref.file_id, ref.layer_id, session_dir)`；
      否则 `ids = [ref.layer_id]`。
    - 对每个 id：`dsl = await fetch_dsl(file_id, id, token)`；收集 `(screen_name, digest)`（digest 空跳过）。
    - `kept = filter_promo_digests(...)` → 合并为该 url 的 digest 文本。
  - 文档级缓存 `(file_id, page/layer_id)` 避免重复抓。
  - 单 ref 失败 try/except 跳过、记日志。

### Task 3: 噪音过滤接线 + 体量控制

- [ ] **Step 1**：`resolve_specs` 内对每帧 digest 调 `filter_promo_digests`；总输出按 `_MAX_DIGEST` 上限截断（已有常量）。
- [ ] **Step 2**：`uv run ruff check scripts/mastergo_backfill.py src/testcase_generator/stages/parse/mastergo_fetch.py` 干净。

---

## Chunk 3: CLI（login / scan / run）+ DB 回灌

### Task 4: 子命令

- [ ] **Step 1: `login`**（headed 一次性登录）
  - `launch_persistent_context(session_dir, headless=False)` → 打开 mastergo 首页 → 轮询直到 body 不含引导文案（已登录）→ 关闭保存。打印「登录态已保存到 <dir>」。
- [ ] **Step 2: `scan`**（只读，列候选）
  - `SELECT id, title FROM knowledge.documents WHERE content LIKE '%mastergo.com%' AND deleted_at IS NULL`（用 ORM）。打印每文档 id/title + 链接数（`len(extract_mastergo_links)+len(extract_goto_links)`）。
- [ ] **Step 3: `run --doc <uuid> | --all` [--apply]**
  - 取文档 content → `specs = await resolve_specs(content, token, session_dir)`。
  - `block = build_backfill_block(specs)`；`new_content = inject_backfill_block(content, block)`。
  - **dry-run（默认）**：打印 doc/title、抽到的帧数、digest 字数、注入预览前 800 字；**不写库**。
  - **`--apply`**：`content_hash=sha256(new_content)` → `DocumentRepository.update(doc_id, content=new_content, content_hash=...)` → `VectorizePipeline(session).vectorize_document(doc_id)` → commit。打印「已回灌 + 重嵌」。
  - token 来源：`--token` > `settings.mastergo_api_token`（env `MASTERGO_API_TOKEN`）。

- [ ] **Step 4**：`uv run python scripts/mastergo_backfill.py --help` 三子命令可用；`scan` 跑通列出自签书。

---

## Chunk 4: 验证（真实 PRD 全链路）

### Task 5: 自签书端到端 + 零回归 + 安全

- [ ] **Step 1: 登录**：`uv run python scripts/mastergo_backfill.py login`（headed，人工登录一次）。
- [ ] **Step 2: dry-run 自签书**：`run --doc <自签书 uuid>`（不加 --apply）
  Expected：抽到 ≥3 个真实屏（审核记录/新建/列表），digest 含「审核通过/申请签约/您暂无权限/关联原作」等；广告帧（MasterGo MCP）被过滤；**库未变**。
- [ ] **Step 3: apply**：`run --doc <自签书 uuid> --apply`
  Expected：`documents.content` 末尾出现哨兵包裹的「原型规格补全」块；`content_hash` 变化；`embedding_status` 回到 processing→completed。
- [ ] **Step 4: 幂等复跑**：再 `run --doc <同> --apply` → content 仍只有 1 个哨兵块（替换非追加）。
- [ ] **Step 5: 零回归**：对一个**无 mastergo 链接**的 doc 跑 `run --doc <uuid> --apply` → content **逐字节不变**、不报错（无链接→specs 空→不注入）。
- [ ] **Step 6: 未登录兜底**：删/改 `.mastergo_session` 使失效 → `run` page_id 文档 → 明确报「请先 login」、不写库、不崩。
- [ ] **Step 7: 重生成对照（业务验收）**：对自签书触发一次用例生成，确认审核状态机/权限类用例较回灌前增多（人工眼检即可）。

---

## 总验收标准

- [ ] 纯函数单测全过（噪音过滤 / 幂等注入 / resolve mock）。
- [ ] `scan` 正确列出含链接老 PRD；`login` 持久化会话、无头复用成功。
- [ ] 自签书 `run --apply`：page_id → 浏览器枚帧 → getDsl → 规格回灌进 content（实证含"审核通过/您暂无权限"），广告帧被滤除。
- [ ] 幂等：复跑只保留 1 个哨兵块。
- [ ] 零回归：无链接 doc `--apply` 后 content 逐字节不变。
- [ ] 安全：未登录/坏 token/抓取失败 → 不写库、不崩、有清晰日志。
- [ ] `MASTERGO_API_TOKEN` 仅在 `.env`；`.mastergo_session/` 已 gitignore；改动文件 ruff 干净。

## 风险与回退

- **登录态过期**：跑中途失效 → `harvest_frame_ids` 抛 `MgNotLoggedIn`，CLI 提示重跑 `login`；已 apply 的文档不受影响（幂等可补跑）。
- **图层面板 DOM 变更**（MasterGo 改前端）：枚帧器选择器 `data-id/data-offsetleft` 失效 → 返回 `[]`、该文档跳过并告警。属一次性工具+下线源，可接受；必要时回退人工贴 layer_id 链接。
- **写库安全**：默认 dry-run；`--apply` 才写；哨兵幂等可重跑；回灌仅追加独立块，不改 PRD 原文。
- **彻底回退**：删除 content 里哨兵块（正则）即可还原；或从备份恢复。建议首次 `--apply` 前对目标 doc 的 content 留库备份（CLI 可加 `--backup` 打印原 content 到文件）。
- **不碰热路径**：生成流水线 `mastergo_enabled` 保持关，零运行时影响。

---

## 附：本计划与 v1 的差异

- v1（直连 DSL）被实测证伪：真实链接是 page_id，纯 API 取不到（design §7.1）。
- v2 用「无头浏览器读图层面板枚 frame id → 复用 getDsl」攻克 page_id（design §7.2，已端到端 6809 字实证）。
- 形态从「灰度入热路径」改为「一次性存量迁移 CLI」（用户拍板，MasterGo 将下线）。
- 取数/摘要纯函数全复用 v1 已实现部分，新增仅：浏览器枚帧 + 噪音过滤 + 幂等注入 + DB 回灌 CLI。
