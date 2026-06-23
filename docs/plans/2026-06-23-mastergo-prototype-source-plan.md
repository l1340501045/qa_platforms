# 落点⑦ MasterGo 原型规格接入 Implementation Plan

> **For agentic workers:** REQUIRED: 用 superpowers:executing-plans 执行；步骤用 `- [ ]` 勾选。

**Goal:** 把 PRD 正文里 MasterGo 原型链接背后的结构化规格（字段/控件/状态机等）抽出来、并入对应章节内容，让生成"看得见"这些原本只在原型里的规格——根治"薄 PRD"。**通用化：无链接的 PRD 零影响。**

**Architecture:** 检测 PRD section 内容里的 mastergo.com 链接 → 调官方 DSL 接口（`GET /mcp/dsl`，头 `X-MG-UserAccessToken`）→ 抽文本摘要 → 追加进该 section.content（作为 trust=1 PRD 内容自然流经下游）。灰度默认关、缺 token/无链接/单链接失败均安全跳过、绝不阻断解析。

**Tech Stack:** Python 3.12, asyncio, httpx（openai 传递依赖，已装）, pytest。PoC 已验证接口连通。

> 设计依据：`docs/spec/2026-06-23-mastergo-prototype-source-design.md`。

---

## 现状速查

- `parse/playwright_fetch.py`：`_explore_single_prototype` 是 TODO 占位返回 None（原型链接被忽略）——**本计划新建 `mastergo_fetch.py` 取代它的职责**。
- `parse/node.py::parse_node`（async）：构建 `parsed_context`（含 `sources[].sections[].content`）后、`await classify_sections(...)` 前，是注入点。
- DSL 接口（PoC 实证）：`GET https://mastergo.com/mcp/dsl?fileId=<id>&layerId=<lid>`，头 `X-MG-UserAccessToken: <token>` + `Content-Type/Accept: application/json`；返回 `{styles, nodes, components}`；TEXT 节点文本在 `node["text"]=[{"text":...}]`，屏/容器是 `type=="FRAME"` 带 `name`。
- URL 解析：fileId = 路径 `/file/<digits>`；layerId = query `layer_id`（值含冒号如 `90:420043`，请求时 URL 编码）。
- 配置样式：`settings.py` 布尔默认关 + `.env` 同名大写覆盖。`.env` 已有 `LLM_API_TOKEN` 等先例。
- 验证素材：自签书（**含**链接，doc `1cc71668…`/sys `e1cc33d7…`，§6.2 正文有 mastergo 链接）；漫剧（**无** mastergo 链接，零回归基准）。

## File Structure

- **Modify** `src/platform_api/core/settings.py`：`mastergo_enabled: bool = False` + `mastergo_api_token: str = ""`。
- **Create** `src/testcase_generator/stages/parse/mastergo_fetch.py`：链接解析 + DSL 拉取 + 摘要 + 章节富化编排（失败兜底）。
- **Modify** `src/testcase_generator/stages/parse/node.py`：parse_node 在 classify 前调富化（仅开关开且有 token 时）。
- **Modify** `.env`：加 `MASTERGO_API_TOKEN=`（**不提交**）。
- **Create** `tests/testcase_generator/test_mastergo_fetch.py`：链接解析 + DSL→摘要 + 富化兜底（mock）。
- **Create**（验证）`.qa_probe/mastergo_before_after.py`：自签书富化前后 + 漫剧零回归 + 坏 token 兜底。

---

## Chunk 1: 配置 + 取数模块

### Task 1: 配置项

- [ ] **Step 1**：`settings.py` 新增（紧挨现有开关）：
```python
    # ── 原型多源接地（落点⑦）：MasterGo 原型 DSL 规格接入 ──────────────────────
    # 关：忽略 PRD 里的 MasterGo 链接（行为不变）。开：拉原型 DSL、抽规格并入章节内容。
    # 无链接/无 token/单链接失败均安全跳过，绝不阻断解析。
    mastergo_enabled: bool = False
    mastergo_api_token: str = ""  # env MASTERGO_API_TOKEN，勿提交
```
- [ ] **Step 2**：`uv run python -c "from src.platform_api.core.settings import settings; print(settings.mastergo_enabled)"` → `False`。

### Task 2: `mastergo_fetch.py`（TDD 纯函数 + 取数 + 编排）

- [ ] **Step 1: 写纯函数测试（先失败）** — `tests/testcase_generator/test_mastergo_fetch.py`
```python
from src.testcase_generator.stages.parse.mastergo_fetch import (
    extract_mastergo_links, dsl_to_spec_digest,
)


def test_extract_links():
    c = "管理端见原型 https://mastergo.com/file/171777687959897?fileOpenFrom=project&page_id=68%3A91864&layer_id=90%3A420043 完"
    refs = extract_mastergo_links(c)
    assert len(refs) == 1
    assert refs[0].file_id == "171777687959897"
    assert refs[0].layer_id == "90:420043"


def test_extract_none():
    assert extract_mastergo_links("没有任何原型链接的普通文本") == []


def test_digest_from_dsl():
    dsl = {"nodes": [{"type": "FRAME", "name": "审核列表", "children": [
        {"type": "TEXT", "name": "x", "text": [{"text": "审核状态"}]},
        {"type": "TEXT", "name": "y", "text": [{"text": "待提审"}, {"text": "/审核通过"}]},
    ]}]}
    d = dsl_to_spec_digest(dsl)
    assert "审核状态" in d and "待提审" in d
    assert dsl_to_spec_digest({"nodes": []}) == ""
```
Run → FAIL（模块不存在）。

- [ ] **Step 2: 实现 `mastergo_fetch.py`**
```python
"""落点⑦ — MasterGo 原型 DSL 规格接入。检测 PRD 里的 mastergo 链接 → 拉 DSL → 抽规格摘要 → 并入章节内容。
通用化：无链接/无 token/失败均安全跳过，绝不阻断解析。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_DSL_URL = "https://mastergo.com/mcp/dsl"
_FILE_RE = re.compile(r"https?://mastergo\.com/file/(\d+)[^\s)\]]*", re.I)
_LAYER_RE = re.compile(r"[?&]layer_id=([^&\s)\]]+)", re.I)
_TIMEOUT = 30
_MAX_DIGEST = 4000


@dataclass(frozen=True)
class MgRef:
    url: str
    file_id: str
    layer_id: str


def extract_mastergo_links(content: str) -> list[MgRef]:
    """从文本抽 MasterGo /file/ 链接（含 fileId + layer_id）。无则返回 []。"""
    refs: list[MgRef] = []
    seen: set[tuple[str, str]] = set()
    for m in _FILE_RE.finditer(content or ""):
        url = m.group(0)
        file_id = m.group(1)
        lm = _LAYER_RE.search(url)
        if not lm:
            continue
        layer_id = httpx.URL(f"http://x/?layer_id={lm.group(1)}").params.get("layer_id") or lm.group(1)
        key = (file_id, layer_id)
        if key in seen:
            continue
        seen.add(key)
        refs.append(MgRef(url=url, file_id=file_id, layer_id=layer_id))
    return refs


def dsl_to_spec_digest(dsl: dict, max_chars: int = _MAX_DIGEST) -> str:
    """遍历 DSL，按屏/容器分组抽 TEXT 文本，去重输出可读摘要。空则 ''。"""
    nodes = (dsl or {}).get("nodes") or []

    def texts_of(node: dict, acc: list[str]) -> None:
        if not isinstance(node, dict):
            return
        if node.get("type") == "TEXT":
            s = "".join(seg.get("text", "") for seg in (node.get("text") or []) if isinstance(seg, dict)).strip()
            if s:
                acc.append(s)
        for c in (node.get("children") or []):
            texts_of(c, acc)

    screens: list[tuple[str, list[str]]] = []
    for top in nodes:
        children = top.get("children") or [top]
        for screen in children:
            acc: list[str] = []
            texts_of(screen, acc)
            if acc:
                screens.append((screen.get("name") or "screen", acc))

    seen: set[str] = set()
    lines: list[str] = []
    for name, acc in screens:
        uniq = [t for t in acc if not (t in seen or seen.add(t))]
        if uniq:
            lines.append(f"· {name}：" + " / ".join(uniq))
    return "\n".join(lines)[:max_chars]


async def fetch_dsl(file_id: str, layer_id: str, token: str) -> dict:
    """调官方 DSL 接口。抛异常由调用方兜底。"""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-MG-UserAccessToken": token,
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(_DSL_URL, params={"fileId": file_id, "layerId": layer_id}, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def enrich_sections_with_mastergo(sources: list, token: str) -> int:
    """原地：把每个 section 内容里的 MasterGo 原型规格摘要追加进该 section.content。
    返回成功富化的链接数。单链接失败跳过、记日志、不抛。
    """
    if not token:
        return 0
    enriched = 0
    for src in sources:
        for sec in getattr(src, "sections", []) or []:
            refs = extract_mastergo_links(sec.content or "")
            for ref in refs:
                try:
                    dsl = await fetch_dsl(ref.file_id, ref.layer_id, token)
                    digest = dsl_to_spec_digest(dsl)
                    if digest:
                        sec.content = (sec.content or "") + f"\n\n【原型规格（来自 MasterGo 设计稿）】\n{digest}"
                        enriched += 1
                except Exception as e:  # noqa: BLE001 — 单链接失败跳过，不阻断解析
                    logger.warning("MasterGo 原型拉取失败，跳过 %s: %s", ref.url, e)
    if enriched:
        logger.info("MasterGo 原型规格已并入 %d 个链接", enriched)
    return enriched
```
- [ ] **Step 3**：`uv run pytest tests/testcase_generator/test_mastergo_fetch.py -q` → 纯函数测试全过。

---

## Chunk 2: 集成 parse_node

### Task 3: parse_node 接线

- [ ] **Step 1**：`node.py` 顶部 import `from src.testcase_generator.stages.parse.mastergo_fetch import enrich_sections_with_mastergo`；在 `parsed_context = ParsedContext(...)` 之后、`await classify_sections(parsed_context.sources)` 之前插入：
```python
    # 落点⑦：MasterGo 原型规格接入（仅开关开且有 token；无链接/失败安全跳过）
    if settings.mastergo_enabled and settings.mastergo_api_token:
        await enrich_sections_with_mastergo(parsed_context.sources, settings.mastergo_api_token)
```
- [ ] **Step 2: 零回归**：`uv run pytest tests/testcase_generator/ -q` → 全绿（开关默认关，不触发）。

---

## Chunk 3: 验证

### Task 4: 三态验证（含链接富化 / 无链接零回归 / 坏 token 兜底）

- [ ] **Step 1**：`.env` 加 `MASTERGO_API_TOKEN=<你的有效 mg_ 令牌>`（不提交）。
- [ ] **Step 2**：写 `.qa_probe/mastergo_before_after.py`：对自签书 + 漫剧两 doc，在 `mastergo_enabled` 关/开 下复跑 `parse_node`，对每个 source 的 sections 输出「含『原型规格』标记的章节数 + 内容增量字数」。
- [ ] **Step 3: 跑验证**：`uv run python .qa_probe/mastergo_before_after.py`
  Expected：
  - **自签书（含链接）**：开后有 ≥1 个章节 content 末尾出现「原型规格」摘要，且摘要含"审核状态/待提审"等（实证规格进来了）。
  - **漫剧（无链接）**：开 vs 关 章节内容**逐字节一致**（零影响）。
- [ ] **Step 4: 坏 token 兜底**：临时把 token 改错 → 跑自签书 → section 内容不变、无异常、parse 正常完成（日志有 warning）。
- [ ] **Step 5: ruff**：`uv run ruff check` 改动文件通过。

---

## 总验收标准

- [ ] 开关默认关，`tests/testcase_generator/` 全绿，无链接 PRD parse 逐字节不变。
- [ ] `test_mastergo_fetch.py`：链接解析 / DSL→摘要 / 空兜底 全过。
- [ ] 自签书开关开：含链接章节并入原型规格摘要（探针实证含"审核状态"等）。
- [ ] 坏 token / 无链接：零异常、零内容变化。
- [ ] `MASTERGO_API_TOKEN` 仅在 `.env`、未提交；改动文件 ruff 干净。

## 风险与回退

- **外部依赖/延迟**：每链接 30s 超时 + 失败跳过；链接通常 1-2 个/PRD。
- **令牌安全**：仅 `.env`，不提交/不打印。
- **即时回退**：`MASTERGO_ENABLED=false`（默认即关）→ 完全不触发，零代码回滚。
- **零下游影响**：仅在 parse 富化章节内容；test_points/write_cases/verify 不动。
- **短链 /goto/**：本期只解析 /file/ 直链（自签书即直链）；/goto/ 短链留待后续（需先 GET 取 302）。

---

## GPT Review Findings（2026-06-23）

### 🔴 阻断性：page_id vs layer_id 层级错配

**问题**：真实 PRD 中的 MasterGo 链接全是 `page_id` 格式（如 `?page_id=48%3A74637`），无 `layer_id`。
当前 `extract_mastergo_links` 要求必须有 `layer_id`（`if not lm: continue`）→ 真实链接全被跳过。
PoC 之所以成功，是因为手动点进图层后 URL 才带 `layer_id`——非 PRD 内链接格式。

**影响**：功能对真实自签书 PRD 一条规格都捞不到。

**修复路径**：需 API spike 确认「page_id → Frame 图层清单」的跳转方式：
1. 对 file 根（不传 layerId / 传根 id）`getDsl`，看是否返回页面/Frame 树
2. `/goto/` 短链 302 → 目标 URL 可能带 layer_id
3. MasterGo 是否有「列出页面子节点」的接口

### 🟡 已采纳改进

- **[3]** 加异步 mock 测试覆盖「单链接失败不抛」安全属性
- **[4]** 文档级 `(file_id, page/layer_id)` 缓存，避免重复请求

### 当前状态

骨架代码（灰度开关 + 兜底 + 零回归 + 摘要提取）已实现并通过单测（117 pass）。
**Blocked on**: spike 确认 page→Frame 取数路径后，需修改 `extract_mastergo_links` + `fetch_dsl` + 测试。
