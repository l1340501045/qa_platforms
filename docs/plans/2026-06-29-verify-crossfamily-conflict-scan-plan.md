# verify 跨族核验 + 跨条款矛盾扫描 Implementation Plan

> **✅ 已完成** — commits `21960a7..f1519a3`（7 commits），4 测试全绿，`.env` 已配 `LLM_VERIFY_MODEL=deepseek-v4-pro-office`。
> 关联 spec：`docs/spec/2026-06-29-verify-crossfamily-conflict-scan-design.md`。

**Goal:** 给 verify 关卡换非 Claude 族模型（deepseek，消除 family bias）+ 复用单次调用做跨条款矛盾扫描（抓 PRD 内部自相矛盾），两者均可灰度回滚、零回归。

**Architecture:** `llm_client.generate_structured` 增可选 `model` 参数；verify 用新配置 `llm_verify_model`（留空=回退 primary）。rubric 在开关 `verify_cross_section_conflict_enabled` 打开时注入「跨条款矛盾检查」指令，复用 verify 已检索的 `prd_sections`，输出 `cross_section_conflict`+`conflicting_refs`，`summarize` 汇成 PRD 矛盾清单；verdict/bucket 语义不变。

**Tech Stack:** Python 3.12 / pydantic v2 / pytest（`asyncio_mode=auto`）/ OpenAI 兼容网关。

---

## 现状速查（对齐当前代码）

- `src/platform_api/core/settings.py`：LLM 区（`llm_primary_model` 行 36、`llm_concurrency` 行 43、`llm_timeout` 行 47、`llm_json_mode` 行 53）；灰度开关多在中下部。
- `src/testcase_generator/services/llm_client.py`：`generate_structured`（行 186-286）内 `model = settings.llm_vision_model if images else self.primary_model`（行 201）；`_call(self, model, ...)`（行 288）已按 model 调用。
- `src/testcase_generator/stages/verify/verifier.py`：`_CaseVerdict`（行 63-69）、`_VerifyLLMOutput`（行 71-73）、`_VERDICT_BUCKET`（行 26-31）、`verify_cases`（行 115）内调用 `generate_structured`（行 145-150）、`summarize`（行 187-198）。
- `src/testcase_generator/stages/verify/rubric.py`：`VERIFY_SYSTEM_PROMPT`（行 9-35）。
- `src/testcase_generator/schemas/test_case.py`：`CaseVerification`（行 37-46）、`Verdict`/`Bucket`（行 24/33）。
- `src/testcase_generator/stages/verify/node.py`：`verify_node`（行 102）已构建 `sections_by_feature`（含全局+跨功能点检索），**本计划不改 node**。
- **落库（自审确认）**：`tasks/callbacks.py:125` `verification = case_data.get("verification") or {}`、`:152` `verification=verification or None`（整 dict 落 `test_cases.verification` JSONB），`:150-151` verdict/bucket 取自该 dict。新字段经 `pipeline_task.py:134` 的 `model_dump()` 进入该 dict → **自动落 JSONB，无需改 callbacks、无需迁移**；verdict/bucket 单列不受影响（本计划也不改 verdict）。
- **mock 约定**：`monkeypatch.setattr(mod, "get_llm_client", lambda: fake)`。
- **⚠️ 提交隔离**：工作树有大量其他未提交改动（`llm_client.py` 已是 M）。每次只 `git add` 本计划明确列出的文件，**严禁 `-A` / `git add .`**。

## File Structure

- **Modify** `settings.py` — 2 个配置项（模型名 + 灰度开关）
- **Modify** `llm_client.py` — `generate_structured` 加可选 `model` 参数（不改其他行为）
- **Modify** `schemas/test_case.py` — `CaseVerification` 加 2 字段 + `CrossSectionConflictRef` 子模型
- **Modify** `verify/verifier.py` — `_CaseVerdict` 加字段、传 model、解析回挂、`summarize` 加 PRD 矛盾清单
- **Modify** `verify/rubric.py` — 矛盾检查指令常量（拼接到 system prompt）
- **Create** `tests/testcase_generator/test_verify_cross_section.py` — 单测 + 已知矛盾 fixture 端到端回归
- **Modify** `.env` — 加 `LLM_VERIFY_MODEL`（最后一步，人工确认）
- ~~`scripts/verify_regression.py`~~ — **自审删除**：离线重跑需重建 pipeline `ParsedContext`（feature→source_refs），从 DB 不可行；回归改为 fixture 端到端测试（见 Chunk 3）

---

## Chunk 1: 改① verify 跨族模型（基础设施，最小可用）

### Task 1: `generate_structured` 加可选 `model` 参数（TDD）

**Files:** Modify `src/testcase_generator/services/llm_client.py`；Test: `tests/testcase_generator/test_verify_cross_section.py`

- [x] **Step 1: 写失败测试**（新建测试文件）
```python
"""verify 跨族 + 跨条款矛盾扫描 单测。"""
from __future__ import annotations

import pytest

from src.testcase_generator.services.llm_client import LLMClient


async def test_generate_structured_passes_explicit_model(monkeypatch):
    """传入 model 时，_call 必须收到该 model（而非 primary）。"""
    from pydantic import BaseModel

    class _Out(BaseModel):
        ok: bool

    client = LLMClient.__new__(LLMClient)  # 跳过 __init__ 避免连真网关
    client.primary_model = "claude-primary"
    client._json_mode = False

    seen = {}

    async def fake_call(model, system_prompt, user_content, output_schema, temperature, images=None):
        seen["model"] = model
        return _Out(ok=True)

    monkeypatch.setattr(client, "_call", fake_call)

    await client.generate_structured("sys", "usr", _Out, model="deepseek-x")
    assert seen["model"] == "deepseek-x"

    await client.generate_structured("sys", "usr", _Out)  # 不传 → 回退 primary
    assert seen["model"] == "claude-primary"
```

- [x] **Step 2: 跑测试看失败**
Run: `uv run pytest tests/testcase_generator/test_verify_cross_section.py::test_generate_structured_passes_explicit_model -v`
Expected: FAIL（`generate_structured` 不接受 `model` 关键字 → TypeError）。

- [x] **Step 3: 实现**（`llm_client.py`）
`generate_structured` 签名加 `model: str | None = None`（放在 `images` 之后）：
```python
    async def generate_structured(
        self,
        system_prompt: str,
        user_content: str,
        output_schema: Type[T],
        temperature: float = 0.3,
        images: list[bytes] | None = None,
        model: str | None = None,
    ) -> T:
```
把行 201 的模型选择改为（显式 model 优先，images 次之，最后 primary）：
```python
        model = model or (settings.llm_vision_model if images else self.primary_model)
```
（其余逻辑不变：`_attempt` / `_call` 已用局部变量 `model`。）

- [x] **Step 4: 跑测试看通过**
Run: `uv run pytest tests/testcase_generator/test_verify_cross_section.py::test_generate_structured_passes_explicit_model -v`
Expected: PASS。

- [x] **Step 5: Commit**
```bash
git add src/testcase_generator/services/llm_client.py tests/testcase_generator/test_verify_cross_section.py
git commit -m "feat(llm): generate_structured 支持显式 model 参数（默认回退 primary）"
```

### Task 2: settings 加配置 + verify 用 `llm_verify_model`

**Files:** Modify `src/platform_api/core/settings.py`、`src/testcase_generator/stages/verify/verifier.py`

- [x] **Step 1: settings 加字段**（`llm_json_mode` 行 53 之后）
```python
    # verify 关卡专用模型：留空则回退 llm_primary_model（行为不变）。
    # 设为非 Claude 族（如 deepseek-v4-pro-office）以消除 generator/judge 同族的 self-enhancement bias。
    llm_verify_model: str = ""
```

- [x] **Step 2: settings 加灰度开关**（与其它灰度开关同区，文件中下部）
```python
    # ── verify 跨条款矛盾扫描（cherry-pick）灰度开关 ──────────────────────────
    # 开：verify 在判 verdict 之外，检查 PRD 条款间是否实质互斥（PRD 内部矛盾），
    # 标 cross_section_conflict + 两处出处，汇成 PRD 矛盾清单。关：行为与改造前一致。
    verify_cross_section_conflict_enabled: bool = True
```

- [x] **Step 3: verifier 调用传 model**（`verifier.py` 行 145-150 的 `generate_structured(...)` 加一行）
```python
                out = await get_llm_client().generate_structured(
                    system_prompt=VERIFY_SYSTEM_PROMPT,
                    user_content=user_content,
                    output_schema=_VerifyLLMOutput,
                    temperature=0.1,
                    model=settings.llm_verify_model or None,
                )
```
（`settings` 已在 `verifier.py:18` 导入。）

- [x] **Step 4: 冒烟**
Run: `uv run python -c "from src.platform_api.core.settings import settings; print(repr(settings.llm_verify_model), settings.verify_cross_section_conflict_enabled)"`
Expected: 打印 `'' True`（未配 .env 时留空）。

- [x] **Step 5: 回归不破坏**——跑现有 verify 相关测试
Run: `uv run pytest tests/testcase_generator/ -k verify -v`
Expected: 全 PASS（留空配置 = 行为不变）。

- [x] **Step 6: Commit**
```bash
git add src/platform_api/core/settings.py src/testcase_generator/stages/verify/verifier.py
git commit -m "feat(verify): 支持 llm_verify_model 跨族核验（留空回退 primary）"
```

---

## Chunk 2: 改② 跨条款矛盾扫描

### Task 3: schema 加字段（TDD）

**Files:** Modify `src/testcase_generator/schemas/test_case.py`、`src/testcase_generator/stages/verify/verifier.py`；Test: 同测试文件

- [x] **Step 1: 写失败测试**（追加到测试文件）
```python
def test_case_verification_has_cross_section_fields():
    from src.testcase_generator.schemas.test_case import CaseVerification, CrossSectionConflictRef

    cv = CaseVerification(
        verdict="grounded",
        bucket="main",
        cross_section_conflict=True,
        conflicting_refs=[CrossSectionConflictRef(
            ref_a="§5.6.1", quote_a="≤50字", ref_b="§9.2首表", quote_b="不限字数",
        )],
    )
    assert cv.cross_section_conflict is True
    assert cv.conflicting_refs[0].ref_b == "§9.2首表"
    # 默认值（向后兼容）
    assert CaseVerification().cross_section_conflict is False
    assert CaseVerification().conflicting_refs == []
```

- [x] **Step 2: 跑测试看失败**
Run: `uv run pytest tests/testcase_generator/test_verify_cross_section.py::test_case_verification_has_cross_section_fields -v`
Expected: FAIL（ImportError: CrossSectionConflictRef）。

- [x] **Step 3: 实现**（`test_case.py`，`CaseVerification` 之前加子模型，并在其内加字段）
```python
class CrossSectionConflictRef(BaseModel):
    """跨条款矛盾的一对出处（PRD 两条互斥条款）"""

    ref_a: str = Field(description="条款 A 的章节标识")
    quote_a: str = Field(description="条款 A 原文")
    ref_b: str = Field(description="条款 B 的章节标识")
    quote_b: str = Field(description="条款 B 原文")
```
`CaseVerification` 末尾加：
```python
    cross_section_conflict: bool = Field(
        default=False, description="该用例断言虽被某条款支持，但 PRD 另有条款与之实质互斥（PRD 内部矛盾）"
    )
    conflicting_refs: list[CrossSectionConflictRef] = Field(
        default_factory=list, description="互斥条款对清单（cross_section_conflict=True 时给出）"
    )
```

- [x] **Step 4: verifier 内 `_CaseVerdict` 加对应字段**（`verifier.py` 行 63-69）
```python
class _ConflictRef(BaseModel):
    ref_a: str = ""
    quote_a: str = ""
    ref_b: str = ""
    quote_b: str = ""


class _CaseVerdict(BaseModel):
    case_id: str = Field(description="回填输入中的 case_id")
    verdict: str = Field(description="grounded / conflict / undefined / ungrounded")
    rationale: str = Field(default="", description="判定理由，一句话")
    prd_evidence: str | None = Field(default=None, description="PRD 原文摘录（直接引用）")
    unsupported_assertions: List[str] = Field(default_factory=list, description="无支撑/冲突的具体断言")
    cross_section_conflict: bool = Field(default=False, description="PRD 条款间实质互斥")
    conflicting_refs: List[_ConflictRef] = Field(default_factory=list, description="互斥条款对")
```

- [x] **Step 5: 跑测试看通过**
Run: `uv run pytest tests/testcase_generator/test_verify_cross_section.py::test_case_verification_has_cross_section_fields -v`
Expected: PASS。

- [x] **Step 6: Commit**
```bash
git add src/testcase_generator/schemas/test_case.py src/testcase_generator/stages/verify/verifier.py
git commit -m "feat(verify): CaseVerification/_CaseVerdict 加 cross_section_conflict 字段"
```

### Task 4: rubric 矛盾检查指令（开关控制）

**Files:** Modify `src/testcase_generator/stages/verify/rubric.py`、`src/testcase_generator/stages/verify/verifier.py`

- [x] **Step 1: rubric 加可拼接指令常量**（`rubric.py` 末尾）
```python
CROSS_SECTION_CONFLICT_INSTRUCTION = """

【附加任务 · 跨条款矛盾扫描（PRD 内部自相矛盾）】
除上面的 verdict 外，对每条用例额外检查：所给 prd_sections 中，是否存在两条 PRD 条款【针对同一字段/同一行为】给出【不可同时成立】的规定，且本用例断言命中其一。
- 命中则置 cross_section_conflict=true，并在 conflicting_refs 给出互斥的两处：{ref_a,quote_a,ref_b,quote_b}，quote 必须是 PRD 原文直引。
- 严格控误报：仅「实质互斥」才报。下列情况【不算】矛盾，cross_section_conflict 保持 false：
  · 一处「未提及」、另一处有规定（缺失≠矛盾）；
  · 两处只是详略不同、范围包含、措辞差异；
  · 分属不同字段/不同页面/不同投放方式。
- 与 verdict 解耦：发现矛盾【不改变】verdict 取值（矛盾是 PRD 的问题，不是用例错）。无矛盾时 cross_section_conflict=false、conflicting_refs=[]。"""
```

- [x] **Step 2: verifier 顶部 import 改为同时引入两者**（`verifier.py:21`，替换原单一 import，避免函数内重复 import / F401）
```python
from src.testcase_generator.stages.verify.rubric import (
    CROSS_SECTION_CONFLICT_INSTRUCTION,
    VERIFY_SYSTEM_PROMPT,
)
```

- [x] **Step 3: `verify_cases` 体内算一次 system_prompt**（`verify_cases` 函数体开头、`_verify_batch` 定义之前；闭包捕获，避免每批重复拼接）
```python
    system_prompt = VERIFY_SYSTEM_PROMPT
    if settings.verify_cross_section_conflict_enabled:
        system_prompt += CROSS_SECTION_CONFLICT_INSTRUCTION
```
并把 `_verify_batch` 内 `generate_structured(system_prompt=VERIFY_SYSTEM_PROMPT, ...)` 改为 `system_prompt=system_prompt`。

- [x] **Step 4: 冒烟（开关可读）**
Run: `uv run python -c "from src.platform_api.core.settings import settings; print(settings.verify_cross_section_conflict_enabled)"`
Expected: `True`。

- [x] **Step 5: Commit**
```bash
git add src/testcase_generator/stages/verify/rubric.py src/testcase_generator/stages/verify/verifier.py
git commit -m "feat(verify): rubric 跨条款矛盾检查指令（灰度开关控制注入）"
```

### Task 5: 解析回挂 + summarize 汇总 PRD 矛盾清单（TDD）

**Files:** Modify `src/testcase_generator/stages/verify/verifier.py`；Test: 同测试文件

- [x] **Step 1: 写失败测试**（追加；mock 整个 verify_cases 走假 client）
```python
async def test_verify_cases_attaches_and_summarizes_conflict(monkeypatch):
    from src.testcase_generator.stages.verify import verifier as vmod
    from src.testcase_generator.stages.verify.verifier import (
        PrdSection, VerifyCase, summarize, verify_cases,
    )

    class _FakeOut:
        def __init__(self):
            self.verdicts = [vmod._CaseVerdict(
                case_id="V0", verdict="grounded", rationale="r",
                cross_section_conflict=True,
                conflicting_refs=[vmod._ConflictRef(
                    ref_a="§5.6.1", quote_a="≤50字", ref_b="§9.2", quote_b="不限字数")],
            )]

    class _FakeClient:
        async def generate_structured(self, **kw):
            return _FakeOut()

    monkeypatch.setattr(vmod, "get_llm_client", lambda: _FakeClient())

    cases = [VerifyCase(case_id="V0", feature_id="F1", title="标题包名50字可存")]
    sections = {"F1": [PrdSection("§5.6.1", "≤50字", "§5.6.1"),
                       PrdSection("§9.2", "不限字数", "§9.2")]}
    res = await verify_cases(cases, sections)
    assert res["V0"].cross_section_conflict is True
    assert res["V0"].verdict == "grounded"  # 不被改写

    summ = summarize(res)
    assert summ["cross_section_conflicts"] == 1
    assert len(summ["prd_conflict_list"]) == 1
```

- [x] **Step 2: 跑测试看失败**
Run: `uv run pytest tests/testcase_generator/test_verify_cross_section.py::test_verify_cases_attaches_and_summarizes_conflict -v`
Expected: FAIL（CaseVerification 未带 cross_section_conflict / summarize 无 prd_conflict_list）。

- [x] **Step 3: 实现 — 回挂**（`verifier.py` `_verify_batch` 内构造 `CaseVerification` 处，行 166-172 加 2 字段）
```python
            batch_result[c.case_id] = CaseVerification(
                verdict=verdict,
                bucket=_VERDICT_BUCKET.get(verdict, "needs_spec"),
                rationale=v.rationale,
                prd_evidence=v.prd_evidence,
                unsupported_assertions=v.unsupported_assertions,
                cross_section_conflict=v.cross_section_conflict,
                conflicting_refs=[
                    CrossSectionConflictRef(ref_a=r.ref_a, quote_a=r.quote_a, ref_b=r.ref_b, quote_b=r.quote_b)
                    for r in v.conflicting_refs
                ],
            )
```
在 `verifier.py` 顶部 import 加 `CrossSectionConflictRef`（与 `CaseVerification` 同行 from test_case import）。

- [x] **Step 4: 实现 — summarize**（`verifier.py` `summarize` 行 187-198 扩展）
```python
def summarize(verifications: dict[str, CaseVerification]) -> dict:
    """聚合核验结果分布 + PRD 矛盾清单。"""
    by_verdict: dict[str, int] = defaultdict(int)
    by_bucket: dict[str, int] = defaultdict(int)
    conflict_pairs: dict[tuple, dict] = {}
    for v in verifications.values():
        by_verdict[v.verdict] += 1
        by_bucket[v.bucket] += 1
        if v.cross_section_conflict:
            for r in v.conflicting_refs:
                key = tuple(sorted([(r.ref_a, r.quote_a), (r.ref_b, r.quote_b)]))
                slot = conflict_pairs.setdefault(key, {
                    "ref_a": r.ref_a, "quote_a": r.quote_a,
                    "ref_b": r.ref_b, "quote_b": r.quote_b, "case_count": 0,
                })
                slot["case_count"] += 1
    return {
        "total": len(verifications),
        "by_verdict": dict(by_verdict),
        "by_bucket": dict(by_bucket),
        "cross_section_conflicts": sum(1 for v in verifications.values() if v.cross_section_conflict),
        "prd_conflict_list": list(conflict_pairs.values()),
    }
```

- [x] **Step 5: 跑测试看通过**
Run: `uv run pytest tests/testcase_generator/test_verify_cross_section.py -v`
Expected: 全 PASS。

- [x] **Step 6: 回归全量 verify 测试**
Run: `uv run pytest tests/testcase_generator/ -k verify -v`
Expected: 全 PASS。

- [x] **Step 7: Commit**
```bash
git add src/testcase_generator/stages/verify/verifier.py tests/testcase_generator/test_verify_cross_section.py
git commit -m "feat(verify): 矛盾结论回挂 CaseVerification + summarize 产出 PRD 矛盾清单"
```

---

## Chunk 3: 回归验证（落实成功标准）

> **自审修正**：原"离线重跑整批 verify"不可行——`verify_cases` 需 `prd_sections_by_feature`（按 feature_id 切的 PRD），它由 pipeline `ParsedContext`(feature→source_refs 映射) 构建，从 DB（仅最终用例 + `document.content`）无法简单复原（`audit_export.py` 是按 `source_section` 字符串切，非 feature_id）。故改为**合成「已知矛盾」fixture 端到端验证**：确定性、可重复、不依赖 DB/ParsedContext。「跨族对偏松的纠正」属定性效果，降为可选人工抽样（见末尾）。

### Task 6: 已知矛盾 fixture 端到端验证（TDD）

**Files:** Test: `tests/testcase_generator/test_verify_cross_section.py`（追加；文件顶部确保 `import json`）

- [x] **Step 1: 写测试**——用审查确认的 3 对 PRD 矛盾构造 fixture，mock client 依据 system_prompt 是否含矛盾指令决定是否报矛盾，断言「开关→指令→召回」因果链 + summarize 清单
```python
async def test_known_prd_conflicts_recalled_end_to_end(monkeypatch):
    """审查已知的 3 对 PRD 矛盾：开关开 → 指令注入 → verify_cases 召回 cross_section_conflict。"""
    from src.testcase_generator.stages.verify import verifier as vmod
    from src.testcase_generator.stages.verify.verifier import (
        PrdSection, VerifyCase, summarize, verify_cases,
    )

    known = [
        ("F1", "标题包名称恰好50字可保存", "§5.6.1", "标题包名称 ≤ 50 字", "§9.2", "标题包包名 不限字数"),
        ("F2", "包名含emoji被自动剔除", "§5.0.3", "emoji 自动剔除并提示", "§5.6.1", "emoji 保存时弹错"),
        ("F3", "同投手定向包重名禁止保存", "§5.0.5", "重名禁止保存", "§5.7.1", "同投手不重名 mock 仅弱校验"),
    ]
    cases, sections = [], {}
    for i, (fid, title, ra, qa, rb, qb) in enumerate(known):
        cases.append(VerifyCase(case_id=f"V{i}", feature_id=fid, title=title))
        sections[fid] = [PrdSection(ra, qa, ra), PrdSection(rb, qb, rb)]

    class _FakeClient:
        async def generate_structured(self, *, system_prompt, user_content, output_schema, **kw):
            inject = "跨条款矛盾扫描" in system_prompt  # 仅指令注入时才报矛盾
            payload = json.loads(user_content)
            verdicts = []
            for tc in payload["test_cases"]:
                secs = payload["prd_sections"]
                verdicts.append(vmod._CaseVerdict(
                    case_id=tc["case_id"], verdict="grounded",
                    cross_section_conflict=inject,
                    conflicting_refs=[vmod._ConflictRef(
                        ref_a=secs[0]["source_ref"], quote_a=secs[0]["content"],
                        ref_b=secs[1]["source_ref"], quote_b=secs[1]["content"],
                    )] if inject else [],
                ))
            return vmod._VerifyLLMOutput(verdicts=verdicts)

    monkeypatch.setattr(vmod, "get_llm_client", lambda: _FakeClient())
    monkeypatch.setattr(vmod.settings, "verify_cross_section_conflict_enabled", True)

    res = await verify_cases(cases, sections)
    assert sum(1 for v in res.values() if v.cross_section_conflict) == 3
    assert len(summarize(res)["prd_conflict_list"]) == 3

    # 对照：开关关 → 指令不注入 → 召回 0（验证因果链）
    monkeypatch.setattr(vmod.settings, "verify_cross_section_conflict_enabled", False)
    res0 = await verify_cases(cases, sections)
    assert sum(1 for v in res0.values() if v.cross_section_conflict) == 0
```

- [x] **Step 2: 跑测试**（实现已在 Chunk 1/2 完成）
Run: `uv run pytest tests/testcase_generator/test_verify_cross_section.py -v`
Expected: 全 PASS。

- [x] **Step 3: Commit**
```bash
git add tests/testcase_generator/test_verify_cross_section.py
git commit -m "test(verify): 已知 PRD 矛盾 fixture 端到端召回（开关因果链）"
```

### 可选 · 真实效果验证（人工，不入 CI）

- **deepseek 识别能力 smoke**：临时配 `LLM_VERIFY_MODEL=deepseek-v4-pro-office`，对上面 3 对 fixture 用**真实** client（去 mock）跑一次，确认 deepseek 真能识别矛盾、JSON 稳定。
- **跨族纠偏抽样**：对 batch `0c9b63e6` 审查标注偏松的 §8.2「关键行为」用例，用 deepseek 重判抽查 5~10 条，人工对比是否不再误判 grounded（不入自动回归——需重建 ParsedContext）。

---

## 最后一步（人工）：启用配置

- [x] 在 `.env` 增加（确认网关 `llm.xk-devops.com` 已支持该模型名）：
```
LLM_VERIFY_MODEL=deepseek-v4-pro-office
# verify 跨条款矛盾扫描默认已开；如需关闭：VERIFY_CROSS_SECTION_CONFLICT_ENABLED=false
```
- [x] 重启 celery worker 使配置生效；对新批次或回归脚本验证。

## Execution Handoff

Plan 完成并保存到 `docs/plans/2026-06-29-verify-crossfamily-conflict-scan-plan.md`。
执行建议：Chunk 1 → Chunk 2 → Chunk 3 顺序执行；每个 Task 走 TDD（红→绿→commit）；**提交隔离铁律：只 add 本计划列出的文件**。
