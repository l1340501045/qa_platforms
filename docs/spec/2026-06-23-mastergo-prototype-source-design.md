# 落点⑦ · MasterGo 原型规格接入 — 设计文档

> 状态：设计（brainstorming 产出，PoC 已验证）。下一步：writing-plans 出实施计划 → 灰度实现 → 验证。
> 关联：roadmap 落点⑦「多源接地·原型」；progress.md 通用性铁律；替换 `parse/playwright_fetch.py` 的 TODO 占位。

## 1. 背景与目标

实测发现用户 PRD「薄」的根因：**大量交互/逻辑规格不在 PRD 正文，而在 MasterGo 原型里**（正文只写"见原型 + 链接"）。当前 `playwright_fetch._explore_single_prototype` 是 TODO 占位、返回 None → **MasterGo 链接被完全忽略** → 规格进不来 → 覆盖度低、用例空壳。

**PoC 已证明可行**：用官方 DSL 接口（`GET https://mastergo.com/mcp/dsl`，头 `X-MG-UserAccessToken`，fileId+layerId 取自 URL），从一个原型图层捞回 128 条规格文本（字段名、控件、Tab、**审核状态机 待提审/等待审批/审核通过/审核不通过/润稿修改**）。

**目标**：把 PRD 里 MasterGo 原型的结构化规格抽出来、并入 PRD 内容，让生成"看得到"这些规格。

**成功标准**：
- 含 MasterGo 链接的 PRD（自签书）：链接所在章节内容被补入原型规格（审核状态机/字段等），生成能据此出实质用例。
- **不含链接的 PRD：行为与现状逐字节一致**（零影响）。
- 任一链接拉取失败：跳过该链接、不阻断解析。

## 2. 范围

**做**：检测 PRD 正文里的 MasterGo 链接 → 拉 DSL → 抽规格摘要 → 并入该章节内容。
**不做**：其他原型工具（Figma/蓝湖/Axure，留扩展口不实现）；不改下游生成逻辑；不做完整设计稿还原（只抽可测规格文本/结构）。

## 3. 设计

### 3.1 通用化保证（硬要求）

- 检测：正则扫描 section 内容里的 `mastergo.com/file/<fileId>?...layer_id=<layerId>` 及 `/goto/<short>` 短链。
- **0 链接 → 完全跳过**：不调 API、不改内容、行为逐字节不变。
- 总开关 `settings.mastergo_enabled`（默认关）+ `MASTERGO_API_TOKEN`（缺失即跳过）。
- 单链接失败（无权限/超时/草稿箱/非团队文件）→ try/except 跳过该链接、记 warning、继续其余、绝不抛出。

### 3.2 取数（`parse/mastergo_fetch.py`，替换 playwright 占位）

- `extract_mastergo_links(content) -> list[MgRef]`：从文本抽 `(url, file_id, layer_id)`；短链先 GET 取 302 location 再解析（仿官方 `extractIdsFromUrl`）。
- `async fetch_dsl(file_id, layer_id, token) -> dict`：`GET https://mastergo.com/mcp/dsl?fileId=&layerId=`，头 `X-MG-UserAccessToken / Content-Type / Accept`，超时 30s。
- `dsl_to_spec_digest(dsl) -> str`：遍历 `nodes` 树，按 FRAME（屏/容器）分组收集 TEXT（`text[].text` 拼接）+ 节点 name；去重；输出可读 markdown 摘要（屏名 + 字段/文案/状态值清单）。控制体量（如上限 ~4000 字）。

### 3.3 集成（`parse/node.py`）

- parse_node（async）在构建 `parsed_context` 后、`classify_sections` 前，对每个 source 的每个 section：若 `mastergo_enabled` 且 content 含 MasterGo 链接 → `await` 拉取并把摘要**追加进该 section.content**（形如 `\n\n【原型规格(来自 MasterGo)】\n...`）。
- 选择「并入章节内容」而非「新增信源」的理由：规格落在 PRD 指向它的那一节，作为 trust=1 的 PRD 内容自然流经 comprehend/test_points/write_cases/verify 全链路，**无需改下游 / 无信任级flow 复杂度**。

### 3.4 配置

- `settings.mastergo_enabled: bool = False`；`settings.mastergo_api_token: str = ""`（env `MASTERGO_API_TOKEN`，**不提交**）。

## 4. 验证

- **含链接**（自签书 doc `1cc71668…`）：开关开后，含链接章节 content 末尾出现原型规格摘要（审核状态机/字段）；探针对照 before/after。
- **零回归**：不含链接的 PRD（如漫剧）开关开 vs 关，section 内容一致（无链接→不触发）。
- **兜底**：故意用坏 token → 拉取失败、section 内容不变、parse 不崩。
- 单测：`extract_mastergo_links` 解析各种 URL；`dsl_to_spec_digest` 对样例 DSL 产出含关键文本；fetch 失败兜底。

## 5. 风险与缓解

- **外部延迟**：每链接 30s 超时 + 失败跳过；链接通常少（1-2 个/PRD）。
- **令牌安全**：仅 `.env`，不提交、不打印。
- **原型 vs PRD 冲突**：摘要并入 PRD 内容，PRD 正文与原型同级呈现给 LLM；现有 verify/信任仲裁仍以 PRD 正文为准。
- **DSL 体量**：只抽文本摘要（~1.5KB 级）、设上限，不灌全量 DSL。

## 6. 验收标准

- [ ] `mastergo_enabled` 默认关；关闭 / 无 token / 无链接 → parse 行为逐字节不变。
- [ ] `mastergo_fetch.py`：链接解析 + DSL 拉取 + 摘要 + 失败兜底（不抛）。
- [ ] 自签书 PRD 开关开：含链接章节并入原型规格摘要（探针实证含"审核状态"等）。
- [ ] 坏 token / 无链接：零异常、零内容变化。
- [ ] 令牌仅在 `.env`；改动文件 ruff 干净。

---

## 7. 实测结论与架构升级（2026-06-24）

### 7.1 关键发现：真实链接是 page_id，纯 API 取不到

GPT review 的 🔴 阻断点被实测确认：**真实 PRD 里的 MasterGo 链接只带 `page_id`**（如 `?page_id=68%3A91864`），不带 `layer_id`。而：

- `getDsl(fileId, page_id)` → 返回 `nodes=[]`（空）。`getMeta` / `design-texts` / `design-svgs` 同样空（需客户端预热缓存）。
- MasterGo 官方 **OpenAPI**（`developers.mastergo.com/rest-api/`）只有组织/文档/组件/样式管理类接口，**无「列出页面下所有 Frame 节点」的能力**；`resource/preview` 仅私有化部署可用。
- 浏览器抓 HTTP 包：文档节点树**不在 JSON 里**（走 WebSocket/二进制 CRDT 流），拦截不可行。

**结论：SaaS 版上，page_id → 规格没有任何纯 API 路径。** 唯一可自动化的是「模拟客户端」。

### 7.2 攻克：无头浏览器读「图层面板 DOM」枚举 Frame（已端到端验证）

MasterGo 编辑器左侧**图层面板是 HTML（非 canvas）**，每个节点是带 `data-id`（即 layer_id）的 div：

```html
<div nodename="90:420043" data-id="90:420043" data-offsetleft="0" data-haschild="true" data-isclose="true">
```

- `data-offsetleft="0"` 标顶层帧（页面直属屏）；虚拟列表需滚动收全。
- **已用 Playwright（仓库现成依赖）+ 持久化登录态，无头跑通**：`page_id=68:91864` → 枚举出 7 个顶层 frame layer_id。
- 把这些 id 喂回**已跑通的 `getDsl` + `dsl_to_spec_digest`** → **6809 字真实规格**（审核状态机 `[审核通过][申请签约][签约失败]…`、权限规则「非责编点新建→您暂无权限」、字段取值范围、列表页查询项）。

**最终架构**：浏览器只用来解决「page_id → [frame layer_id...]」这一跳；取数与摘要全复用现有纯函数。无需视觉模型，无需拦 WS。

### 7.3 落地形态：一次性存量迁移工具（用户拍板）

MasterGo 即将下线、后续 PRD 基本不再用它，但存量 PRD 需沉淀。故**不进生成热路径**，做成独立 CLI：

```
扫 knowledge.documents.content 里含 mastergo.com 的老 PRD
  → 抽链接（page_id/layer_id/goto）
  → page_id 用浏览器枚 frame id；layer_id 直接用
  → getDsl 每帧 → 摘要 → 过滤 MasterGo 自带广告稿
  → 幂等回灌进 documents.content（带哨兵标记）+ 重算 content_hash + 重嵌
```

- 登录态：一次性 headed 登录 → 持久化 `.mastergo_session`（gitignore），之后无头复用。
- 安全：默认 `--dry-run` 只打印不写库；`--apply` 才落库。
- 噪音：MasterGo 模板/广告帧（"MasterGo MCP / Editorial Architecture / 赋予 AI 掌控画布"）按标记词过滤。

详见实施计划 `docs/plans/2026-06-23-mastergo-prototype-source-plan.md`（v2）。
