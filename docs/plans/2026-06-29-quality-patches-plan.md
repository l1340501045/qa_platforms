# 用例质量三小补丁 Implementation Plan

> **For agentic workers:** REQUIRED: 用 superpowers:subagent-driven-development 或 superpowers:executing-plans 执行；步骤 `- [ ]`。
> 关联 spec：`docs/spec/2026-06-29-quality-patches-design.md`。线 C（3 线之一）：三个互不依赖小补丁，3 个独立 Chunk 可任意顺序执行。

**Goal:** ④导出按 bucket 分流占位用例到「需求澄清清单」；⑤图归位编号失败时语义匹配章节（治影子重复）；⑥边界用例字数声明与输入不符时告警标注。三者独立、零回归。

**Tech Stack:** Python 3.12 / pydantic v2 / openpyxl / pytest（asyncio_mode=auto）。

---

## 现状速查
- `platform_api/tasks/export_task.py`：`_execute_export`（:50，查询 :83 只排 deleted）、`_generate_markdown`（:152）、`_generate_excel`（:199）；`TestCase.verdict`/`.bucket` 列已存在（models/testcase.py:107-108）。
- `knowledge_base/services/image_caption/content_injector.py`：`inject_captions`（:19），section_line_map 编号匹配（:53-61）、归位（:66-85）、附录兜底（:88-93）。
- `testcase_generator/stages/write_cases/node.py`：用例构造 :500-514，`confidence_note=confidence_note`（:512）。
- **⚠️ 提交隔离**：只 `git add` 本计划文件，严禁 `-A`。

## File Structure
- **Modify** `platform_api/tasks/export_task.py`（④）
- **Modify** `knowledge_base/services/image_caption/content_injector.py`（⑤）
- **Create** `testcase_generator/stages/write_cases/length_check.py`、**Modify** `write_cases/node.py`（⑥）
- **Create** `tests/`：`test_export_split.py`、`test_image_relocation.py`、`test_length_check.py`

---

## Chunk 1: 补丁④ 导出占位分流

### Task 1: `_split_cases` + 双 sheet/段（TDD）

**Files:** Modify `export_task.py`；Test: `tests/platform_api/test_export_split.py`

- [ ] **Step 1: 写失败测试**
```python
"""导出占位分流单测。"""
from __future__ import annotations
from types import SimpleNamespace

from src.platform_api.tasks.export_task import _split_cases


def _c(bucket):
    return SimpleNamespace(bucket=bucket, verdict=None, title="t")


def test_split_main_vs_clarification():
    cases = [_c("main"), _c("needs_spec"), _c("to_fix"), _c(None)]
    main, clar = _split_cases(cases)
    # needs_spec → 清单；main/to_fix/None → 主集
    assert len(clar) == 1
    assert len(main) == 3
```

- [ ] **Step 2: 跑失败** → `uv run pytest tests/platform_api/test_export_split.py -v`（_split_cases 不存在）

- [ ] **Step 3: 实现 `_split_cases`**（export_task.py，模块级函数）
```python
def _split_cases(cases: list) -> tuple[list, list]:
    """按 bucket 分流：needs_spec（待补规格/澄清占位）→ 清单；其余→主用例集。
    旧批次 bucket 为 None → 归主集（行为不变）。"""
    main, clarification = [], []
    for c in cases:
        if getattr(c, "bucket", None) == "needs_spec":
            clarification.append(c)
        else:
            main.append(c)
    return main, clarification
```

- [ ] **Step 4: `_execute_export` 用分流**（:89 生成文件前）
```python
            main_cases, clarification_cases = _split_cases(cases)
            if format == "markdown":
                content, content_type, file_ext = _generate_markdown(main_cases, clarification_cases), "text/markdown", "md"
            else:
                content, content_type, file_ext = (
                    _generate_excel(main_cases, clarification_cases),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx",
                )
```
（`total_cases` 仍记 `len(cases)` 或改 `len(main_cases)`——建议记主集数，清单单列。）

- [ ] **Step 5: `_generate_excel`/`_generate_markdown` 加清单参数 + 第二 sheet/段**
```python
def _generate_excel(cases: list, clarification: list | None = None) -> bytes:
    ...  # 原主集 sheet 不变
    if clarification:
        ws2 = wb.create_sheet("需求澄清清单")
        ws2.append(["序号", "标题", "verdict", "判定理由", "PRD依据"])
        for i, c in enumerate(clarification, 1):
            v = c.verification or {}
            ws2.append([i, c.title, getattr(c, "verdict", "") or "",
                        (v or {}).get("rationale", ""), (v or {}).get("prd_evidence", "")])
    ...
```
markdown 同理：主集后追加 `## 需求澄清清单（待 PM 确认，未计入可执行用例）` 段。
（`_generate_excel(cases)` 旧签名加默认 `clarification=None` 保持兼容。）

- [ ] **Step 6: 跑测试通过 + Commit**
```bash
uv run pytest tests/platform_api/test_export_split.py -v
git add src/platform_api/tasks/export_task.py tests/platform_api/test_export_split.py
git commit -m "feat(export): 占位用例(needs_spec)分流到需求澄清清单（主集只留可执行）"
```

---

## Chunk 2: 补丁⑤ 图归位语义匹配

### Task 2: content_injector 语义匹配兜底（TDD）

**Files:** Modify `content_injector.py`；Test: `tests/knowledge_base/test_image_relocation.py`

- [ ] **Step 1: 写失败测试**（section_hint 编号对不上，但 caption 含章节名 → 应归位该章节而非附录）
```python
"""图归位语义匹配单测。"""
from __future__ import annotations

from src.knowledge_base.services.image_caption.content_injector import inject_captions
from src.testcase_generator.schemas.image_caption import ImageCaption


def test_semantic_relocation_when_number_mismatch():
    content = "# 文档\n\n## 5.2 漫剧库\n\n正文。\n\n## 5.9 任务中心\n\n正文。\n"
    cap = ImageCaption(filename="x-20-dramas.png", kind="screen",
                       caption_text="漫剧库列表页面，展示漫剧 id/名称", section_hint="20")  # 编号 20 对不上 5.2
    out = inject_captions(content, [cap])
    # 应归到「5.2 漫剧库」标题下，而非文末附录
    assert "附：未定位图描述" not in out
    lines = out.split("\n")
    drama_idx = next(i for i, l in enumerate(lines) if "5.2 漫剧库" in l)
    assert any("漫剧库列表页面" in l for l in lines[drama_idx:drama_idx + 4])
```
（自审：`ImageCaption.kind` 必填无默认，测试已给 `kind="screen"`；`caption_text` 必填已给；`content_injector` 用 `caption_text`/`ui_elements` 字段名已核对存在。）

- [ ] **Step 2: 跑失败** → 当前编号匹配 miss → 进附录 → 测试 FAIL

- [ ] **Step 3: 实现语义匹配**（`content_injector.py`，第 2 步归位逻辑）
在 section_line_map 旁建标题文本索引：
```python
    heading_text_map: list[tuple[str, int]] = []  # (标题纯文本, 行号)
    for i, line in enumerate(lines):
        hm = _HEADING_RE.match(line)
        if hm:
            text = re.sub(r"[§\d.\s]+", "", hm.group(2))  # 去编号/空格，留语义词
            if text:
                heading_text_map.append((text, i))
            nums = re.findall(r"§?([\dA-Za-z]+(?:\.\d+)*)", hm.group(2))
            for n in nums:
                section_line_map[n] = i
```
归位判定改为「编号命中 OR 语义命中」：
```python
    def _locate(cap: ImageCaption) -> int | None:
        if cap.section_hint and cap.section_hint in section_line_map:
            return section_line_map[cap.section_hint]
        blob = (cap.caption_text or "")
        # 最长标题词匹配（caption 含该章节名）
        best = None
        for text, line_i in heading_text_map:
            if len(text) >= 2 and text in blob:
                if best is None or len(text) > best[0]:
                    best = (len(text), line_i)
        return best[1] if best else None

    for cap in remaining:
        loc = _locate(cap)
        (placed if loc is not None else unplaced).append(cap)
    placed_with_line = [(_locate(cap), cap) for cap in placed]  # 复用
```
（`placed_with_line` 用 `_locate` 结果；其余插入/附录逻辑不变。）

- [ ] **Step 4: 跑测试通过 + Commit**
```bash
uv run pytest tests/knowledge_base/test_image_relocation.py -v
git add src/knowledge_base/services/image_caption/content_injector.py tests/knowledge_base/test_image_relocation.py
git commit -m "feat(image): 图归位编号失败时语义匹配章节标题（治未定位图影子重复）"
```

---

## Chunk 3: 补丁⑥ 边界字数自校验

### Task 3: length_check + write_cases 接入（TDD）

**Files:** Create `write_cases/length_check.py`；Modify `write_cases/node.py`；Test: `tests/testcase_generator/test_length_check.py`

- [ ] **Step 1: 写失败测试**
```python
"""边界字数自校验单测。"""
from __future__ import annotations

from src.testcase_generator.stages.write_cases.length_check import check_step_lengths


def test_mismatch_warns():
    steps = [{"action": "输入20个字符", "input_data": "一二三四五六七八九十一二三四五六", "expected_result": ""}]  # 16 字
    w = check_step_lengths(steps)
    assert w and "20" in w[0]


def test_match_no_warn():
    steps = [{"action": "输入5个字", "input_data": "一二三四五", "expected_result": ""}]
    assert check_step_lengths(steps) == []


def test_no_claim_no_warn():
    steps = [{"action": "点击保存", "input_data": "无", "expected_result": "成功"}]
    assert check_step_lengths(steps) == []
```

- [ ] **Step 2: 跑失败** → 模块不存在 FAIL

- [ ] **Step 3: 实现 `length_check.py`**
```python
"""边界用例字数自校验：step 声称「N 字/字符」时校验 input_data 实际字符数，不符则告警。
不改写用例（避免误伤），仅返回告警供 confidence_note 标注。"""
from __future__ import annotations

import re

_CLAIM_RE = re.compile(r"(\d+)\s*个?\s*(?:字符|字)")


def _visible_len(s: str) -> int:
    """可见字符数（去空白）。中文/英文均按 1 计。"""
    return len(re.sub(r"\s", "", s or ""))


def check_step_lengths(steps: list[dict]) -> list[str]:
    warnings: list[str] = []
    for idx, s in enumerate(steps or [], 1):
        text = f"{s.get('action','')} {s.get('expected_result','')}"
        m = _CLAIM_RE.search(text)
        if not m:
            continue
        claimed = int(m.group(1))
        actual = _visible_len(s.get("input_data", ""))
        # 仅当 input_data 像「被计数的串」（非"无"/空且无明显单位词）才比对
        if actual > 0 and actual != claimed:
            warnings.append(f"步骤{idx}字数声明与输入不符：声称{claimed}实为{actual}")
    return warnings
```

- [ ] **Step 4: write_cases 接入 confidence_note**（`node.py:512` 构造前）
```python
                    from src.testcase_generator.stages.write_cases.length_check import check_step_lengths
                    _len_warn = check_step_lengths([s.model_dump() for s in llm_case.steps])
                    if _len_warn:
                        confidence_note = ((confidence_note or "") + " | " + "；".join(_len_warn)).strip(" |")
```
（放在 `trust_level, confidence_note = confidence_scorer.score(provenance)` 之后、`GeneratedTestCase(...)` 之前。）

- [ ] **Step 5: 跑测试通过 + write_cases 回归 + Commit**
```bash
uv run pytest tests/testcase_generator/test_length_check.py -v
uv run pytest tests/testcase_generator/ -k write_cases -q
git add src/testcase_generator/stages/write_cases/length_check.py src/testcase_generator/stages/write_cases/node.py tests/testcase_generator/test_length_check.py
git commit -m "feat(write_cases): 边界用例字数自校验（声明与输入不符→confidence_note 告警，不改写）"
```

---

## Execution Handoff
3 个 Chunk 互不依赖，可任意顺序/并行执行；每 Task TDD（红→绿→commit）；**提交隔离只 add 本计划文件**。
真实验证：⑤重跑 parse 看「未定位图」附录是否大减；④导出某批次看主集/清单分离；⑥看边界用例 confidence_note 告警。
