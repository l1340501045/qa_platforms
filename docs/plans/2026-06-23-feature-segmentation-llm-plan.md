# 切分通用化（LLM 大纲分段）Implementation Plan

> **For agentic workers:** REQUIRED: 用 superpowers:executing-plans 执行；步骤用 `- [ ]` 勾选跟踪。

**Goal:** 让功能点切分不再死认 `##` 层级——用 LLM 对「标题大纲树」判定功能点边界（自适应粒度），嵌套结构 PRD（功能在 `###/####`）也能正确切；规整 PRD 零回归。

**Architecture:** hybrid「LLM-regex」——正则确定性切出标题三元组（不变）；开关开时 LLM 对大纲（仅标题+字数+短预览，不喂全文）打角色标（功能点根/包裹/元信息/图示），确定性折叠按 LLM 角色执行；开关关或 LLM 失败 → 回退现有 `_choose_feature_level` 规则。灰度默认关、`temperature=0`、绝不阻断解析。

**Tech Stack:** Python 3.12, asyncio, `get_llm_client().generate_structured`, pydantic, pytest。

> 设计依据：`docs/spec/2026-06-23-feature-segmentation-llm-design.md`（已评审）。

---

## 现状速查（实现前必读）

- `src/testcase_generator/stages/parse/node.py`：
  - `_extract_sections(result, doc_type)`（line ~262）：`re.split` 标题正则 → `triples: list[(level, heading, body)]` → `_choose_feature_level(triples)` 选层级 → 折叠循环（`level <= feature_level` = 新功能边界；更深折叠进当前；`_is_meta_heading(heading)` 命中则丢该标题及子树）。
  - `_choose_feature_level`（line ~245）：≥3 个二级标题→层级2（除非同源→1），否则 1。← **要被 LLM 替代的死规则**。
  - `parse_node`（async，line 46）：对 `retrieval_ctx.merged_results` 每个 result 调 `_extract_sections(result, doc_type)`（sync）。
- **可镜像的同类 LLM 模式**：`src/testcase_generator/stages/parse/section_classifier.py`（`classify_sections`：批量 `generate_structured` + 失败 fail-open + 原地改写）。新 `feature_segmenter.py` 仿它写。
- **开关样式**：`src/platform_api/core/settings.py`，布尔默认关（如 `global_section_llm_enabled`）。
- **LLM 客户端**：`get_llm_client().generate_structured(system_prompt, user_content, output_schema, temperature)`。
- **验证素材**：漫剧（规整 `##`，doc `f91a9bef…`/sys `26ffd7ba…`）；自签书（嵌套，doc `1cc71668…`/sys `e1cc33d7…`）。探针参考 `.qa_probe/check_features.py`。

## File Structure

- **Modify** `src/platform_api/core/settings.py`：新增 `feature_seg_llm_enabled: bool = False`。
- **Create** `src/testcase_generator/stages/parse/feature_segmenter.py`：LLM 大纲打角色 + 失败兜底。
- **Modify** `src/testcase_generator/stages/parse/node.py`：抽 `_parse_triples`；`_extract_sections` 接受可选 `roles`；`parse_node` 开关开时 await 调 segmenter。
- **Create** `tests/testcase_generator/test_feature_segmenter.py`：segmenter 单测（mock LLM + 兜底）+ `_extract_sections` 角色驱动折叠测试。
- **Create**（验证）`.qa_probe/seg_before_after.py`：开/关两档对照功能点清单（漫剧零回归 + 自签书正确切）。

> 约束：只改「怎么切功能点」，不动下游 test_points/write_cases/verify 的消费方式。

---

## Chunk 1: 开关 + 重构（零行为变化）

### Task 1: 新增灰度开关

- [ ] **Step 1**：`settings.py` 紧挨 `global_section_llm_enabled` 后新增：
```python
    # ── 功能点切分去死板（LLM 大纲分段，切分通用化）──────────────────────────────
    # 关：用 _choose_feature_level 死规则(## = 功能点)。开：LLM 按大纲语义定功能点边界
    # （自适应粒度，嵌套 PRD 也能正确切）。LLM 失败回退死规则。默认关，行为不变。
    feature_seg_llm_enabled: bool = False
```
- [ ] **Step 2**：`uv run python -c "from src.platform_api.core.settings import settings; print(settings.feature_seg_llm_enabled)"` → `False`。

### Task 2: 重构 `_extract_sections`（抽 triples + 角色驱动，默认行为不变）

**Files:** Modify `src/testcase_generator/stages/parse/node.py`；Test `tests/testcase_generator/test_feature_segmenter.py`

- [ ] **Step 1: 写「重构后零回归 + 角色驱动」测试（先失败）**
```python
# tests/testcase_generator/test_feature_segmenter.py
from src.testcase_generator.stages.parse.node import _parse_triples, _extract_sections


class _R:  # 鸭子 SearchResult
    def __init__(self, content, title="DOC"):
        self.content_snippet = content
        self.title = title


_NESTED = "# 六\n\n## 6.3 功能方案\n\n### 书籍状态\n状态机A\n\n### 作家管理\n管理B\n\n## 6.1 流程图\n图\n"


def test_triples_parsed():
    t = _parse_triples(_NESTED)
    assert [h for _l, h, _b in t] == ["六", "6.3 功能方案", "书籍状态", "作家管理", "6.1 流程图"]


def test_roles_drive_boundaries():
    # roles: idx 2(书籍状态)/3(作家管理)=feature_root；idx1(功能方案)=container；idx4(流程图)=background
    t = _parse_triples(_NESTED)
    roles = {i: "background" for i in range(len(t))}
    roles[2] = "feature_root"; roles[3] = "feature_root"; roles[1] = "container"
    secs = _extract_sections(_R(_NESTED), "prd", roles=roles)
    headings = [s.heading for s in secs]
    assert "书籍状态" in headings and "作家管理" in headings  # 真功能各成一节
    assert "6.1 流程图" not in headings                      # background 丢弃


def test_roles_none_is_legacy():
    # roles=None → 走旧 _choose_feature_level，行为与现状一致（不抛、能切）
    secs = _extract_sections(_R(_NESTED), "prd", roles=None)
    assert len(secs) >= 1
```
Run: `uv run pytest tests/testcase_generator/test_feature_segmenter.py -q` → FAIL（`_parse_triples` 不存在 / `_extract_sections` 无 `roles` 参数）。

- [ ] **Step 2: 重构 `_extract_sections`**
  - 抽出 `def _parse_triples(content: str) -> list[tuple[int, str, str]]`：把现有「`re.split` + 组装三元组」逻辑搬进来（**与现状逐字节同逻辑**）。
  - `_extract_sections(result, doc_type, *, roles: dict[int, str] | None = None)`：
    - `triples = _parse_triples(result.content_snippet)`；无 heading 结构时维持现有「整篇一节」兜底。
    - `roles is None`（旧路）：`feature_level = _choose_feature_level(triples)`；`is_boundary(i, level) = level <= feature_level`；`is_drop(i, heading) = _is_meta_heading(heading)`。
    - `roles` 给定（新路）：`is_boundary(i) = roles.get(i)=="feature_root"`；`is_drop(i) = roles.get(i) in ("meta","background")`；`container` 既非边界也不丢（其 body 折进下一个 root）。
    - 折叠循环复用现有逻辑（meta/丢弃子树跳过、深层折叠进 current、`_flush` 产 `SectionExtract`），只把「边界判定」「丢弃判定」换成上面两个开关。
- [ ] **Step 3**：`uv run pytest tests/testcase_generator/test_feature_segmenter.py -q` → 3 passed。
- [ ] **Step 4: 全量零回归**：`uv run pytest tests/testcase_generator/ -q` → 全绿（`roles=None` 默认路径行为不变）。

---

## Chunk 2: LLM 大纲分段器

### Task 3: `feature_segmenter.py`

**Files:** Create `src/testcase_generator/stages/parse/feature_segmenter.py`；扩充 `test_feature_segmenter.py`

- [ ] **Step 1: 写 segmenter 单测（mock LLM + 兜底，先失败）**
```python
import pytest
from unittest.mock import patch
from src.testcase_generator.stages.parse import feature_segmenter as fseg


@pytest.mark.asyncio
async def test_segmenter_returns_roles(monkeypatch):
    triples = [(1, "六", ""), (2, "6.3 功能方案", ""), (3, "书籍状态", "x"), (2, "6.1 流程图", "图")]

    class _Out:
        classifications = [
            type("C", (), {"idx": 1, "role": "container"})(),
            type("C", (), {"idx": 2, "role": "feature_root"})(),
            type("C", (), {"idx": 3, "role": "feature_root"})(),  # 注：mock 简化，真实按内容判
            type("C", (), {"idx": 0, "role": "meta"})(),
        ]
    async def fake(**kw):
        return _Out()
    with patch.object(fseg.get_llm_client(), "generate_structured", side_effect=fake):
        roles = await fseg.decide_feature_roles("DOC", triples)
    assert roles.get(2) == "feature_root"


@pytest.mark.asyncio
async def test_segmenter_fallback_on_error():
    triples = [(2, "A", "x")]
    async def boom(**kw):
        raise RuntimeError("llm down")
    with patch.object(fseg.get_llm_client(), "generate_structured", side_effect=boom):
        roles = await fseg.decide_feature_roles("DOC", triples)
    assert roles == {}   # 失败返回空 → 调用方回退死规则
```
Run → FAIL（模块不存在）。

- [ ] **Step 2: 实现 `feature_segmenter.py`**（镜像 `section_classifier.py`）：
```python
"""功能点切分去死板 — LLM 对标题大纲判角色，定功能点边界（切分通用化）。
只喂大纲(标题+层级+字数+短预览)，不喂全文。失败 fail-open 返回空 → 调用方回退死规则。
"""
from __future__ import annotations

import json
import logging
from typing import List

from pydantic import BaseModel, Field

from src.testcase_generator.services.llm_client import get_llm_client

logger = logging.getLogger(__name__)

_PREVIEW = 120
_VALID_ROLES = {"feature_root", "container", "meta", "background"}

SEG_SYSTEM_PROMPT = """角色：你是需求文档结构分析员。给你一份 PRD 的「标题大纲」（每个标题含层级、文本、正文字数、正文前若干字预览）。
任务：为每个标题判定角色，用于把文档切成「功能点」。角色四选一：
- feature_root：一个【可独立测试的业务功能】的根。其完整规格（含更深子标题内容）应折叠成一个功能点。
- container：仅是包裹/分组标题（如"功能详细说明 / 功能方案 / 需求详述"），本身不是功能点——真正的功能点在它的子标题里。
- meta：非功能信息（版本信息 / 变更日志 / 目录 / 名词解释 / 需求背景 / 需求范围模板占位等）。
- background：流程图 / 交互原型图 / 示意图 等，不含可测规格。

判定要点（与领域无关，只看结构与语义）：
- 「一个可独立测试的业务功能」= 一个 feature_root，粒度自适应：规整文档功能常在二级标题；嵌套文档功能常在三/四级标题（某个 container 下）。
- container 下若有多个各讲不同功能的子标题，则每个子标题判 feature_root（不要把它们糊成一个）。
- 拿不准时判 feature_root（宁可多切，不可把真功能误判成 meta 丢掉）。
- 纯包裹标题判 container；纯图/原型判 background；纯元信息判 meta。

输出：严格按 JSON Schema，对每个输入标题给一条 {idx, role}。"""


class _RoleOut(BaseModel):
    idx: int = Field(description="回填输入标题的 idx")
    role: str = Field(description="feature_root/container/meta/background")


class _SegOutput(BaseModel):
    classifications: List[_RoleOut] = Field(description="每个标题的角色")


async def decide_feature_roles(doc_title: str, triples: list[tuple[int, str, str]]) -> dict[int, str]:
    """LLM 对大纲打角色，返回 {idx: role}。失败/空 → 返回 {}（调用方回退死规则）。"""
    if not triples:
        return {}
    outline = [
        {"idx": i, "level": lv, "heading": h, "body_chars": len(b or ""), "preview": (b or "")[:_PREVIEW]}
        for i, (lv, h, b) in enumerate(triples)
    ]
    try:
        out = await get_llm_client().generate_structured(
            system_prompt=SEG_SYSTEM_PROMPT,
            user_content=json.dumps({"doc_title": doc_title, "outline": outline}, ensure_ascii=False, indent=2),
            output_schema=_SegOutput,
            temperature=0.0,
        )
    except Exception as e:  # noqa: BLE001 — 失败回退死规则，不阻断解析
        logger.warning("功能点切分 LLM 失败，回退死规则: %s", e)
        return {}
    roles: dict[int, str] = {}
    for c in out.classifications:
        role = (c.role or "").strip().lower()
        if 0 <= c.idx < len(triples) and role in _VALID_ROLES:
            roles[c.idx] = role
    if not any(r == "feature_root" for r in roles.values()):
        logger.warning("功能点切分 LLM 未识别出任何 feature_root，回退死规则")
        return {}
    return roles
```
- [ ] **Step 3**：`uv run pytest tests/testcase_generator/test_feature_segmenter.py -q` → 全 passed。

---

## Chunk 3: 集成 + 验证

### Task 4: `parse_node` 接线

**Files:** Modify `src/testcase_generator/stages/parse/node.py`

- [ ] **Step 1**：`parse_node` 里，对每个 result 调 `_extract_sections` 处改为：
```python
        roles = None
        if settings.feature_seg_llm_enabled:
            roles = await decide_feature_roles(result.title, _parse_triples(result.content_snippet))
        sections = _extract_sections(result, doc_type, roles=roles or None)
```
（顶部 import `decide_feature_roles`；确认 `settings` 已导入。`roles or None`：空 dict → None → 走死规则兜底。）
- [ ] **Step 2**：`uv run pytest tests/testcase_generator/ -q` → 全绿（开关默认关，零回归）。

### Task 5: 验证（零回归 + 通用）

**Files:** Create `.qa_probe/seg_before_after.py`

- [ ] **Step 1**：写对照探针：对漫剧 + 自签书两份 doc，分别在 `feature_seg_llm_enabled` 关/开 下复跑 `parse_node`，dump 功能点清单（id/name/source_ref）。
- [ ] **Step 2: 跑验证**：`uv run python .qa_probe/seg_before_after.py`
  Expected：
  - **漫剧**：开 vs 关 功能点集合一致/等价（零回归）。
  - **自签书**：关=「1 blob(6.3 功能方案) + 6 伪功能」；开=「6.3 下的真功能（书籍状态/基础信息/作家管理…）各成功能点，流程图/原型图/版本信息不再是功能点」。
- [ ] **Step 3: ruff**：`uv run ruff check` 改动文件通过。

---

## 总验收标准

- [ ] 开关默认关，`tests/testcase_generator/` 全绿，`_extract_sections(roles=None)` 行为逐字节不变。
- [ ] `test_feature_segmenter.py`：triples 重构 / 角色驱动折叠 / segmenter mock / 失败兜底 全过。
- [ ] 开关开：自签书功能点按真功能正确切分（探针实证）。
- [ ] 开关开：漫剧零回归（功能点等价，探针实证）。
- [ ] 下游消费方式未变；ruff 干净。

## 风险与回退

- **非确定性**：`temperature=0` + 灰度 + 死规则兜底；规整 PRD 有零回归测试。
- **LLM 漏判真功能**：prompt 从宽（拿不准判 feature_root）+ 探针人工核对清单。
- **即时回退**：`FEATURE_SEG_LLM_ENABLED=false`（默认即关）→ 走死规则，零代码回滚。
- **零下游影响**：仅改功能点切分；test_points/write_cases/verify 不动。
