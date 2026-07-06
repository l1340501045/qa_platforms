# 切分通用化（LLM 大纲分段）Implementation Plan

> **For agentic workers:** REQUIRED: 用 superpowers:executing-plans 执行；步骤用 `- [ ]` 勾选跟踪。
> **v2（2026-06-24 修订）**：现状变化——验证样本改用合成 fixture，避免绑定单份真实 PRD；行号对齐当前代码。

**Goal:** 让功能点切分不再死认 `##` 层级——用 LLM 对「标题大纲树」判定功能点边界（自适应粒度），嵌套结构 PRD（功能在 `###/####`）也能正确切；规整 PRD 零回归。

**Architecture:** hybrid「LLM-regex」——正则确定性切出标题三元组（不变）；开关开时 LLM 对大纲（仅标题+层级+字数+短预览，不喂全文）打角色标（功能点根/包裹/元信息/图示），确定性折叠按 LLM 角色执行；开关关或 LLM 失败 → 回退现有 `_choose_feature_level` 死规则。灰度默认关、`temperature=0`、绝不阻断解析。

**Tech Stack:** Python 3.12, asyncio, `get_llm_client().generate_structured`, pydantic, pytest。

> 设计依据：`docs/spec/2026-06-23-feature-segmentation-llm-design.md`（已评审）。

---

## 现状速查（实现前必读，已对齐当前代码）

- `src/testcase_generator/stages/parse/node.py`（真实行号）：
  - `_is_meta_heading(heading)`@214：命中变更日志/背景/目标等非功能词 → 该标题及子树丢弃。
  - `_second_level_cohesive(triples)`@229：判二级章节是否「同源」（共享判别性术语≥阈值）。
  - `_choose_feature_level(triples)`@250：≥3 个二级标题→层级 2（除非 `_second_level_cohesive` 同源→1），否则 1。← **要被 LLM 替代的死规则（含 cohesion 子判定，roles=None 时整体保留）**。
  - `_extract_sections(result, doc_type)`@267：`re.split` 标题正则 → `triples: list[(level, heading, body)]` → `_choose_feature_level` 选层级 → 折叠循环（`level <= feature_level` = 新功能边界；更深折叠进 current；`_is_meta_heading` 命中丢标题及子树）。读 `result.content_snippet`；无 heading 时整篇兜底一节。
  - `parse_node`（async）@47：对 `retrieval_ctx.merged_results` 每个 result 调 `_extract_sections(result, doc_type)`（sync，约 @83）。
- **content_snippet 口径**（`src/knowledge_base/services/retrieval_service.py`）：**seed 文档 content_snippet=全文**（line 56 `content_snippet=seed_doc.content`）；关联文档=截断 ~200 字。→ 切分只对 seed 全文有实际意义，关联文档大纲极短、segmenter 近似 no-op（成本可忽略）。
- **可镜像的同类 LLM 模式**：`src/testcase_generator/stages/parse/section_classifier.py`（`classify_sections`：批量 `generate_structured` + 失败 fail-open + 原地改写）。新 `feature_segmenter.py` 仿它写。
- **开关样式**：`src/platform_api/core/settings.py`，布尔默认关（紧邻已有生成质量灰度开关）。
- **LLM 客户端**：`get_llm_client().generate_structured(system_prompt, user_content, output_schema, temperature)`。
- **验证素材（v2 改动）**：用**合成 fixture**（自带嵌套结构，确定性、不依赖 DB、不绑单份 PRD）做正确性验证 + **真 LLM 冒烟**；零回归用**全量测试套件**（`roles=None` 路径逐字节不变即证）。漫剧真实 doc 回归为**可选**（DB 起时跑）。

## File Structure

- **Modify** `src/platform_api/core/settings.py`：新增 `feature_seg_llm_enabled: bool = False`。
- **Create** `src/testcase_generator/stages/parse/feature_segmenter.py`：LLM 大纲打角色 + 失败兜底。
- **Modify** `src/testcase_generator/stages/parse/node.py`：抽 `_parse_triples`；`_extract_sections` 加可选 `roles`；`parse_node` 开关开时 await 调 segmenter。
- **Create** `tests/testcase_generator/test_feature_segmenter.py`：segmenter 单测（mock LLM + 兜底）+ `_extract_sections` 角色驱动折叠测试。
- **Create**（验证）`.qa_probe/seg_smoke.py`：合成嵌套 PRD 上跑「真 LLM segmenter → 角色 → 切分」端到端冒烟。

> 约束：只改「怎么切功能点」，不动下游 test_points/write_cases/verify 的消费方式。

---

## Chunk 1: 开关 + 重构（零行为变化）

### Task 1: 新增灰度开关

**Files:** Modify `src/platform_api/core/settings.py`

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
from src.testcase_generator.stages.parse.node import _extract_sections, _parse_triples


class _R:  # 鸭子 SearchResult（_extract_sections 只用 content_snippet + title）
    def __init__(self, content, title="DOC"):
        self.content_snippet = content
        self.title = title


_NESTED = "# 六\n\n## 6.3 功能方案\n\n### 书籍状态\n状态机A\n\n### 作家管理\n管理B\n\n## 6.1 流程图\n图\n"


def test_triples_parsed():
    t = _parse_triples(_NESTED)
    assert [h for _l, h, _b in t] == ["六", "6.3 功能方案", "书籍状态", "作家管理", "6.1 流程图"]


def test_roles_drive_boundaries():
    # 文档标题"六"与"6.3 功能方案"=container(跳过不成节)；书籍状态/作家管理=feature_root；流程图=background(丢)
    # ⚠️ 文档标题(level1)不可标 meta——meta 丢整棵子树会把其下所有功能一并丢掉，应标 container。
    t = _parse_triples(_NESTED)
    roles = {0: "container", 1: "container", 2: "feature_root", 3: "feature_root", 4: "background"}
    secs = _extract_sections(_R(_NESTED), "prd", roles=roles)
    headings = [s.heading for s in secs]
    assert "书籍状态" in headings and "作家管理" in headings  # 真功能各成一节
    assert "6.1 流程图" not in headings                      # background 丢弃
    assert "6.3 功能方案" not in headings and "六" not in headings  # container 不单独成节


def test_roles_none_is_legacy():
    # roles=None → 走旧 _choose_feature_level，行为与现状一致（不抛、能切）
    secs = _extract_sections(_R(_NESTED), "prd", roles=None)
    assert len(secs) >= 1
```
- [ ] **Step 2: 跑测试，确认失败** — `uv run pytest tests/testcase_generator/test_feature_segmenter.py -q` → FAIL（`_parse_triples` 不存在 / `_extract_sections` 无 `roles` 参数）。

- [ ] **Step 3: 重构 `_extract_sections`**
  - 抽出 `def _parse_triples(content: str) -> list[tuple[int, str, str]]`：把现有 `re.split` 标题正则 + 组装三元组逻辑搬进来（**与现状逐字节同逻辑**；空/无 heading 返回 `[]`）。
  - `_extract_sections(result, doc_type, *, roles: dict[int, str] | None = None)`：
    - `content = result.content_snippet`；空→`[]`；`triples = _parse_triples(content)`；`triples` 空→维持「整篇一节」兜底。
    - `roles is None`（旧路）：`feature_level = _choose_feature_level(triples)`；边界 `is_boundary(level) = level <= feature_level`；丢弃 `is_drop(heading) = _is_meta_heading(heading)`。**逐字节等价现状**。
    - `roles` 给定（新路）：
      - `is_boundary(i) = roles.get(i) == "feature_root"` → `_flush()` 关旧节 + 开新 current。
      - `is_drop(i) = roles.get(i) in ("meta", "background")` → `_flush()` + `skip_below_level = level`（丢该标题及整棵子树，复用现有 meta 子树跳过逻辑）。
      - `container` 或未标（含文档标题等纯包裹）→ **跳过该标题本身**（`continue`：不成节、不丢子树、不动 current），其子标题在后续迭代按各自角色处理。因只有 feature_root 才 `_flush`+开节，container 不会被误 flush 成空节。
    - 折叠循环复用现有逻辑（`skip_below_level` 子树跳过、深层 heading 折叠进 current、`_flush` 产 `SectionExtract`），只把「边界判定」「丢弃判定」「跳过判定」按上面三类切换。
- [ ] **Step 4: 跑测试，确认通过** — `uv run pytest tests/testcase_generator/test_feature_segmenter.py -q` → 3 passed。
- [ ] **Step 5: 全量零回归** — `uv run pytest tests/testcase_generator/ -q` → 全绿（`roles=None` 默认路径行为不变）。
- [ ] **Step 6: Commit（只加切分文件）**
```bash
git add src/platform_api/core/settings.py src/testcase_generator/stages/parse/node.py tests/testcase_generator/test_feature_segmenter.py
git commit -m "refactor(parse): 抽 _parse_triples + _extract_sections 角色驱动（切分通用化骨架，灰度关零回归）"
```

---

## Chunk 2: LLM 大纲分段器

### Task 3: `feature_segmenter.py`

**Files:** Create `src/testcase_generator/stages/parse/feature_segmenter.py`；扩充 `tests/testcase_generator/test_feature_segmenter.py`

- [ ] **Step 1: 写 segmenter 单测（mock LLM + 兜底，先失败）**
```python
import pytest
from unittest.mock import patch

from src.testcase_generator.stages.parse import feature_segmenter as fseg


@pytest.mark.asyncio
async def test_segmenter_returns_roles():
    triples = [(1, "六", ""), (2, "6.3 功能方案", ""), (3, "书籍状态", "x"), (2, "6.1 流程图", "图")]

    class _Out:
        classifications = [
            type("C", (), {"idx": 1, "role": "container"})(),
            type("C", (), {"idx": 2, "role": "feature_root"})(),
            type("C", (), {"idx": 3, "role": "background"})(),
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
Run: `uv run pytest tests/testcase_generator/test_feature_segmenter.py -q` → 新增 2 条 FAIL（模块不存在）。

- [ ] **Step 2: 实现 `feature_segmenter.py`**（镜像 `section_classifier.py`）：
```python
"""功能点切分去死板 — LLM 对标题大纲判角色，定功能点边界（切分通用化）。
只喂大纲(标题+层级+字数+短预览)，不喂全文。失败 fail-open 返回空 → 调用方回退死规则。
"""
from __future__ import annotations

import json
import logging

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
- container 下若有多个各讲不同功能的子标题，则每个子标题判 feature_root（不要糊成一个）。
- 拿不准时判 feature_root（宁可多切，不可把真功能误判成 meta 丢掉）。
- 纯包裹标题判 container；纯图/原型判 background；纯元信息判 meta。

输出：严格按 JSON Schema，对每个输入标题给一条 {idx, role}。"""


class _RoleOut(BaseModel):
    idx: int = Field(description="回填输入标题的 idx")
    role: str = Field(description="feature_root/container/meta/background")


class _SegOutput(BaseModel):
    classifications: list[_RoleOut] = Field(description="每个标题的角色")


async def decide_feature_roles(doc_title: str, triples: list[tuple[int, str, str]]) -> dict[int, str]:
    """LLM 对大纲打角色，返回 {idx: role}。失败/未识别出任何 feature_root → 返回 {}（调用方回退死规则）。"""
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
- [ ] **Step 4: Commit（只加切分文件）**
```bash
git add src/testcase_generator/stages/parse/feature_segmenter.py tests/testcase_generator/test_feature_segmenter.py
git commit -m "feat(parse): LLM 大纲分段器 decide_feature_roles（切分通用化，失败兜底）"
```

---

## Chunk 3: 集成 + 验证

### Task 4: `parse_node` 接线

**Files:** Modify `src/testcase_generator/stages/parse/node.py`

- [ ] **Step 1**：顶部 import `from src.testcase_generator.stages.parse.feature_segmenter import decide_feature_roles`（确认 `settings` 已导入）。`parse_node` 里对每个 result 调 `_extract_sections` 处改为：
```python
        roles = None
        if settings.feature_seg_llm_enabled:
            roles = await decide_feature_roles(result.title, _parse_triples(result.content_snippet))
        sections = _extract_sections(result, doc_type, roles=roles or None)
```
（`roles or None`：空 dict → None → 走死规则兜底。）
- [ ] **Step 2: 全量零回归** — `uv run pytest tests/testcase_generator/ -q` → 全绿（开关默认关）。
- [ ] **Step 3: Commit** — `git add src/testcase_generator/stages/parse/node.py && git commit -m "feat(parse): parse_node 接线 LLM 切分（灰度开关 feature_seg_llm_enabled）"`

### Task 5: 验证（零回归 + 合成嵌套正确切 + 真 LLM 冒烟）

**Files:** Create `.qa_probe/seg_smoke.py`

> v2 改动理由：为避免「绑单份 PRD」，正确性用**合成嵌套 fixture** + **真 LLM** 验证；零回归用 Task 4 Step 2 的全量测试套件（`roles=None` 路径不变即证）。

- [ ] **Step 1: 写真 LLM 冒烟探针** `.qa_probe/seg_smoke.py`：
  - 内置一个**合成嵌套 PRD 字符串**（仿真实嵌套：`# 文档 / ## N 功能详述(container) / ### 功能A(feature) / ### 功能B(feature) / ## 流程图(background) / ## 版本记录(meta)`）。
  - `triples = _parse_triples(SYN)`；`roles = await decide_feature_roles("合成PRD", triples)`（**真 LLM**，需 `LLM_API_KEY`）。
  - 打印 `roles`；`secs = _extract_sections(_R(SYN), "prd", roles=roles)`；打印功能点 heading 清单。
  - 断言式打印：功能A/功能B 各成节、流程图/版本记录被丢、container 不单独成节。
- [ ] **Step 2: 跑冒烟** — `uv run python .qa_probe/seg_smoke.py`
  Expected：LLM 把 ### 功能A/功能B 判 `feature_root`、container 判 `container`、流程图判 `background`、版本记录判 `meta`；切分结果恰为 [功能A, 功能B]。若 LLM 判错 → 调 `SEG_SYSTEM_PROMPT` 后重试（≤3 轮，仍不稳则记录并升级人工）。
- [ ] **Step 3:（可选）真实规整 PRD 零回归** — 若 DB 起且有规整 doc（如漫剧），临时 `FEATURE_SEG_LLM_ENABLED` 开/关各复跑 `parse_node`，对比功能点集合等价。DB 未起则跳过，以 Task 4 Step 2 全量测试为零回归依据。
- [ ] **Step 4: ruff** — `uv run ruff check src/testcase_generator/stages/parse/feature_segmenter.py src/testcase_generator/stages/parse/node.py src/platform_api/core/settings.py tests/testcase_generator/test_feature_segmenter.py` 干净。

---

## 总验收标准

- [ ] 开关默认关，`tests/testcase_generator/` 全绿，`_extract_sections(roles=None)` 行为逐字节不变（零回归）。
- [ ] `test_feature_segmenter.py`：triples 重构 / 角色驱动折叠 / segmenter mock / 失败兜底 全过。
- [ ] 真 LLM 冒烟（合成嵌套 fixture）：### 子功能各成功能点、流程图/版本记录被丢、container 不单独成节（探针实证）。
- [ ] 下游消费方式未变；改动文件 ruff 干净。
- [ ] **提交隔离**：每次 commit 只含切分相关文件。

## 风险与回退

- **非确定性**：`temperature=0` + 灰度 + 死规则兜底；规整路径有全量零回归测试。
- **LLM 漏判真功能**：prompt 从宽（拿不准判 feature_root）+ 冒烟探针人工核对。
- **通用性验证有限**：当前仅合成 fixture + 漫剧（规整）可验；**多领域嵌套 PRD 的广义鲁棒性待更多真实 PRD 后再测**（与 roadmap 落点③跨 PRD 度量同步推进，本期不阻塞）。
- **即时回退**：`FEATURE_SEG_LLM_ENABLED=false`（默认即关）→ 走死规则，零代码回滚。
- **零下游影响**：仅改功能点切分；test_points/write_cases/verify 不动。
- **提交污染风险**：工作树有其他未提交改动 → 每次 `git add` 用显式文件路径（勿 `git add -A/.`），避免混提。
