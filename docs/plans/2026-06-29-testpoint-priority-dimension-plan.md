# 测试点元数据规范化（优先级 risk 模型 + 维度 enum 收敛）Implementation Plan

> **For agentic workers:** REQUIRED: 用 superpowers:subagent-driven-development 或 superpowers:executing-plans 执行；步骤用 `- [ ]` 勾选跟踪。
> 关联 spec：`docs/spec/2026-06-29-testpoint-priority-dimension-design.md`。线 A（3 线分组之一）。

**Goal:** 优先级改 `risk=likelihood×impact`（取代维度硬映射，治 P0 泛滥 49.7%）；用例维度强制收敛到 `dimensions.yaml` 英文 enum（prompt 约束 + normalize 兜底，治 98 标签中英混杂）。

**Architecture:** test_points 让 LLM 给 likelihood/impact，代码 `risk_to_priority` 算 P0/P1/P2；write_cases 用例 priority 继承 test_point、dimensions 经 `normalize_dimensions` 归一到 enum。均只动元数据派生，不碰覆盖/溯源/verify，旧批次不受影响。

**Tech Stack:** Python 3.12 / pydantic v2 / pytest（asyncio_mode=auto）/ yaml。

---

## 现状速查（对齐当前代码）

- `test_points/node.py`：`GeneratedTestPoint`（:36-43，有 dimension/priority）、`TEST_POINTS_SYSTEM_PROMPT`（:54-71，priority 判定段 :63-67）、`_derive_priority`（:126-140 维度→P0 硬映射，**P0 泛滥根因**）、`_load_dimensions()`（:77）、落点 `_PRIORITY_MAP.get(gtp.priority,..)`（:514-520）、`default_priority` 调用（约 :462）。
- `write_cases/node.py`：`LLMGeneratedCase`（:70-79，priority/dimensions）、`WRITE_CASES_SYSTEM_PROMPT`（:90，中文维度清单 :100-108=**中文标签根因**）、用例构造（:500-514，priority :508、`dimensions=llm_case.dimensions` :509）、`_PRIORITY_MAP`（write_cases 内已有）。
- `config/dimensions.yaml`：`dimensions:` 列表，每项 `name`（英文 enum）+ `category` + 中文 `description` + `check_points`。
- 落库自动兼容：priority/dimensions 经 `callbacks.py` model_dump 落 JSONB，无需迁移。
- **⚠️ 提交隔离**：工作树有大量其他未提交改动。每次只 `git add` 本计划文件，严禁 `-A`。

## File Structure
- **Modify** `test_points/node.py` — risk 字段 + prompt + `risk_to_priority` + 落点替换
- **Modify** `write_cases/node.py` — prompt enum 对齐 + priority 继承 + dimensions normalize
- **Create** `config/dimension_aliases.yaml` — 别名→enum 映射
- **Create** `stages/write_cases/dimension_normalizer.py` — `normalize_dimensions`
- **Create** `tests/.../test_priority_risk.py`、`tests/.../test_dimension_normalize.py`
- **Create** `scripts/metadata_regression.py`

---

## Chunk 1: ①优先级 risk 模型

### Task 1: `risk_to_priority` + schema 字段（TDD）

**Files:** Modify `test_points/node.py`；Test: `tests/testcase_generator/test_priority_risk.py`

- [ ] **Step 1: 写失败测试**
```python
"""优先级 risk 模型单测。"""
from __future__ import annotations

import pytest

from src.testcase_generator.stages.test_points.node import risk_to_priority


@pytest.mark.parametrize("l,i,expected", [
    (3, 3, "P0"), (3, 2, "P0"), (2, 3, "P0"),   # risk 9/6/6
    (2, 2, "P1"), (3, 1, "P1"), (1, 3, "P1"),   # risk 4/3/3
    (1, 2, "P2"), (2, 1, "P2"), (1, 1, "P2"),   # risk 2/2/1
])
def test_risk_to_priority(l, i, expected):
    assert risk_to_priority(l, i) == expected


def test_risk_to_priority_clamps_out_of_range():
    # 越界输入夹紧到 [1,3]，不崩
    assert risk_to_priority(0, 9) in {"P0", "P1", "P2"}
```

- [ ] **Step 2: 跑测试看失败** — `uv run pytest tests/testcase_generator/test_priority_risk.py -v` → FAIL（risk_to_priority 不存在）。

- [ ] **Step 3: 实现**（`test_points/node.py`，`_derive_priority` 上方加）
```python
# risk = likelihood × impact（各 1-3）→ 优先级。阈值可调：P0 需双高（risk≥6）。
P0_MIN_RISK = 6
P1_MIN_RISK = 3


def risk_to_priority(likelihood: int, impact: int) -> str:
    """risk=likelihood×impact 映射 P0/P1/P2（取代维度硬映射，治 P0 泛滥）。"""
    def _clamp(x: int) -> int:
        return max(1, min(3, int(x)))
    risk = _clamp(likelihood) * _clamp(impact)
    if risk >= P0_MIN_RISK:
        return "P0"
    if risk >= P1_MIN_RISK:
        return "P1"
    return "P2"
```

- [ ] **Step 4: schema 加字段**（`GeneratedTestPoint`，:36-43）
```python
class GeneratedTestPoint(BaseModel):
    feature_id: str = Field(description="关联功能 ID")
    dimension: str = Field(description="维度名称")
    description: str = Field(description="具体、可验证的测试点描述")
    priority: str = Field(default="P2", description="（已弃用，改由 likelihood×impact 派生）")
    likelihood: int = Field(default=2, ge=1, le=3, description="易错可能性 1-3")
    impact: int = Field(default=2, ge=1, le=3, description="业务影响 1-3")
    risk_rationale: str = Field(default="", description="likelihood/impact 判定一句话理由")
    derived_from: List[str] = Field(default_factory=list, description="来源引用")
```

- [ ] **Step 5: 落点替换**（:514-520 区域）
```python
        priority = risk_to_priority(gtp.likelihood, gtp.impact)
```
（删除该处 `_PRIORITY_MAP`/`gtp.priority` 用法。`_derive_priority` 若仅 :462 `default_priority` 还在用，将 :462 也改为 `risk_to_priority` 的合理默认或移除该键；`_derive_priority` 函数标注弃用或删除。）

- [ ] **Step 6: 跑测试通过 + verify 全量 test_points 回归**
`uv run pytest tests/testcase_generator/test_priority_risk.py -v` → PASS
`uv run pytest tests/testcase_generator/ -k test_points -q` → PASS（如挂，多因 GeneratedTestPoint 新字段默认值缺失，已给默认值应无碍）

- [ ] **Step 7: Commit**
```bash
git add src/testcase_generator/stages/test_points/node.py tests/testcase_generator/test_priority_risk.py
git commit -m "feat(test_points): 优先级改 risk=likelihood×impact 模型（取代维度硬映射）"
```

### Task 2: prompt 改 risk 指引 + write_cases priority 继承

**Files:** Modify `test_points/node.py`、`write_cases/node.py`

- [ ] **Step 1: test_points prompt 改 risk 指引**（`TEST_POINTS_SYSTEM_PROMPT` :63-67 的「priority 判定」段替换为）
```
- 风险打分（取代固定优先级）：为每个测试点给两个整数（1-3）：
  - impact（业务影响）：3=核心路径/资损/数据完整性/高频功能；2=一般功能；1=边缘/低频。
  - likelihood（易错可能性）：3=边界/异常/复杂逻辑/并发/集成；2=一般分支；1=简单展示。
  - 另给一句 risk_rationale 说明判分依据。优先级由系统按 likelihood×impact 自动计算，你无需再给 priority。
```

- [ ] **Step 2: write_cases priority 继承 test_point**（`write_cases/node.py:508`）
**自审确认**：`_process_feature` 内已有 `tp = tp_map.get(llm_case.test_point_id)`（:468），构造用例时 `tp` 已在作用域，直接复用即可（无需重建字典）：
```python
                            priority=tp.priority if tp else "P2",
```
取代 `priority=_PRIORITY_MAP.get(llm_case.priority, "P2")`（单一事实源=test_point.priority，不再用 LLM 给的 `llm_case.priority`；`_PRIORITY_MAP` 若无其它用处可删）。

- [ ] **Step 3: 冒烟** — `uv run python -c "from src.testcase_generator.stages.test_points.node import risk_to_priority; print(risk_to_priority(3,3), risk_to_priority(1,1))"` → `P0 P2`

- [ ] **Step 4: Commit**
```bash
git add src/testcase_generator/stages/test_points/node.py src/testcase_generator/stages/write_cases/node.py
git commit -m "feat(test_points/write_cases): risk 打分 prompt + 用例优先级继承测试点"
```

---

## Chunk 2: ③维度 enum 收敛

### Task 3: dimension_normalizer + alias 表（TDD）

**Files:** Create `config/dimension_aliases.yaml`、`stages/write_cases/dimension_normalizer.py`；Test: `tests/testcase_generator/test_dimension_normalize.py`

- [ ] **Step 1: 建 alias 表**（`src/testcase_generator/config/dimension_aliases.yaml`，基于审查 98 标签；未列的留给 normalize 告警后补）
```yaml
# 别名（中文/旧标签/英文同义） → dimensions.yaml 的 enum name
aliases:
  正常流: functional_correctness
  数据正确性: functional_correctness
  正确性: functional_correctness
  normal_flow: functional_correctness
  边界值: boundary_value
  boundary: boundary_value
  异常与逆向: invalid_input
  异常输入: invalid_input
  异常流: invalid_input
  异常场景: invalid_input
  异常: invalid_input
  非法值: invalid_input
  abnormal: invalid_input
  exception_handling: invalid_input
  逆向: reversibility
  逆向操作: reversibility
  操作取消: reversibility
  状态机: state_transition
  状态切换: state_transition
  状态变化: state_transition
  正向状态转移: state_transition
  逆向状态转移: state_transition
  状态恢复: recovery
  状态同步: functional_consistency
  并发与一致性: concurrency_state
  一致性: functional_consistency
  数据完整性: data_integrity
  数据精度: data_calculation
  data_accuracy: data_calculation
  权限与可见性: access_control
  水平越权: access_control
  水平越权防护: access_control
  垂直权限: access_control
  数据隔离: access_control
  permission_visibility: access_control
  跨模块联动: cross_system
  联动: cross_system
  cross_module_linkage: cross_system
  实时同步: cross_system
  分页: pagination_boundary
  分页联动: pagination_boundary
  切换交互: ui_interaction
  切换/重选交互: ui_interaction
  UI样式: ui_interaction
  空状态: functional_completeness
  空态: functional_completeness
  幂等与重试: idempotency
  重复操作: idempotency
  防重复提交: idempotency
  默认值: default_values
  必填缺失: invalid_input
  多字节字符: text_length
  特殊字符: invalid_input
  文件格式校验: invalid_input
  日期校验: invalid_input
  emoji处理: invalid_input
  上限: quantity_limit
  刚好等于阈值: boundary_value
  安全: access_control
  安全性: access_control
  接口安全: api_contract
  接口约束: api_contract
  业务规则校验: functional_correctness
  健壮性: recovery
  部分成功: recovery
  文件内重复: invalid_input
```
> **自审已核对**：右侧值均在 `dimensions.yaml` 的 44 个真实 enum 内（`concurrency_state`/`functional_completeness`/`data_integrity`/`data_calculation`/`recovery`/`cross_system`/`access_control`/`state_transition`/`pagination_boundary`/`ui_interaction`/`idempotency`/`default_values`/`text_length`/`quantity_limit`/`api_contract`/`functional_consistency`…）。「兼容性」「需求待确认」无对应 enum 已移除（让其走 `other` 告警，按需再决定是否新增 enum）。

- [ ] **Step 2: 写失败测试**
```python
"""维度 normalize 单测。"""
from __future__ import annotations

from src.testcase_generator.stages.write_cases.dimension_normalizer import normalize_dimensions


def test_enum_passthrough():
    assert normalize_dimensions(["functional_correctness"]) == ["functional_correctness"]


def test_chinese_alias_mapped():
    assert normalize_dimensions(["正常流", "边界值"]) == ["functional_correctness", "boundary_value"]


def test_unknown_goes_other_and_dedup():
    out = normalize_dimensions(["正常流", "正常流", "火星维度"])
    assert out[0] == "functional_correctness"
    assert "other" in out
    assert out.count("functional_correctness") == 1  # 去重保序
```

- [ ] **Step 3: 跑失败** — `uv run pytest tests/testcase_generator/test_dimension_normalize.py -v` → FAIL（模块不存在）

- [ ] **Step 4: 实现** `stages/write_cases/dimension_normalizer.py`
```python
"""把 write_cases LLM 自由填的维度，归一化到 dimensions.yaml 的英文 enum。

未命中 enum 也未命中 alias 的 → 'other' + 告警（暴露漏网标签，便于补 alias 表）。
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_CFG = Path(__file__).resolve().parents[2] / "config"
_DIMENSIONS_PATH = _CFG / "dimensions.yaml"
_ALIASES_PATH = _CFG / "dimension_aliases.yaml"


@lru_cache(maxsize=1)
def _enum_names() -> frozenset[str]:
    data = yaml.safe_load(_DIMENSIONS_PATH.read_text(encoding="utf-8"))
    return frozenset(d["name"] for d in data.get("dimensions", []))


@lru_cache(maxsize=1)
def _aliases() -> dict[str, str]:
    if not _ALIASES_PATH.exists():
        return {}
    data = yaml.safe_load(_ALIASES_PATH.read_text(encoding="utf-8")) or {}
    return dict(data.get("aliases", {}))


def normalize_dimensions(dims: list[str]) -> list[str]:
    """归一到 enum；未命中→'other'+告警。去重保序。"""
    enum, alias = _enum_names(), _aliases()
    out: list[str] = []
    for d in dims or []:
        key = (d or "").strip()
        if key in enum:
            norm = key
        elif key in alias and alias[key] in enum:
            norm = alias[key]
        else:
            logger.warning("未知维度标签 %r → other（建议补 dimension_aliases.yaml）", d)
            norm = "other"
        if norm not in out:
            out.append(norm)
    return out
```

- [ ] **Step 5: 跑测试通过** — `uv run pytest tests/testcase_generator/test_dimension_normalize.py -v` → PASS
（若 `test_chinese_alias_mapped` 因 alias 右值不在 enum 而失败，按 Step1 注修正 alias 右值为真实 enum name。）

- [ ] **Step 6: Commit**
```bash
git add src/testcase_generator/config/dimension_aliases.yaml src/testcase_generator/stages/write_cases/dimension_normalizer.py tests/testcase_generator/test_dimension_normalize.py
git commit -m "feat(write_cases): 维度 normalize 到 dimensions.yaml enum（alias 兜底+other 告警）"
```

### Task 4: write_cases prompt enum 对齐 + 落点接 normalize

**Files:** Modify `write_cases/node.py`

- [ ] **Step 1: prompt 维度清单对齐 enum**（`WRITE_CASES_SYSTEM_PROMPT` :100-108）
把中文维度清单改为「英文 enum（中文释义）」对照，并加硬约束：
```
【dimensions 字段取值约束】dimensions 只能从下列 enum 中选填（英文 name，可多选）：
- functional_correctness（正常流/正确性）、functional_completeness（完整性）、boundary_value（边界值）、
  invalid_input（异常/非法输入）、state_transition（状态机）、access_control（权限可见性）、
  concurrency（并发一致性）、idempotency（幂等重试）、ui_interaction（UI交互）、api_contract（接口契约）、
  cross_system（跨模块联动）… （完整以系统 dimensions.yaml 为准）
严禁自创中文标签或上述之外的词；不确定就选 functional_correctness。
```
（覆盖维度方法论本身可保留，但「输出 dimensions」必须是 enum name。）

- [ ] **Step 2: 落点接 normalize**（`write_cases/node.py:509`）
```python
                            dimensions=normalize_dimensions(llm_case.dimensions),
```
顶部 import：`from src.testcase_generator.stages.write_cases.dimension_normalizer import normalize_dimensions`。

- [ ] **Step 3: 全量 write_cases 回归** — `uv run pytest tests/testcase_generator/ -k write_cases -q` → PASS

- [ ] **Step 4: Commit**
```bash
git add src/testcase_generator/stages/write_cases/node.py
git commit -m "feat(write_cases): prompt 维度对齐 enum + 落点接 normalize_dimensions"
```

---

## Chunk 3: 回归验证

### Task 5: 元数据回归对比脚本

**Files:** Create `scripts/metadata_regression.py`

- [ ] **Step 1: 写脚本**（离线读某批次用例，统计 priority 分布 + 维度标签种类——不需 ParsedContext）
```python
"""线A 回归：统计指定 batch 的 priority 分布 + dimensions 标签种类，对比改造前后。

用法：uv run python scripts/metadata_regression.py <batch_id>
"""
from __future__ import annotations

import asyncio
import sys
from collections import Counter
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from src.platform_api.core.database import get_session_factory  # noqa: E402
from src.platform_api.models.testcase import TestCase  # noqa: E402


async def main() -> None:
    batch_id = UUID(sys.argv[1])
    async with get_session_factory()() as s:
        rows = (await s.execute(select(TestCase).where(TestCase.batch_id == batch_id))).scalars().all()
    n = len(rows)
    prio = Counter(c.priority for c in rows)
    dims = Counter()
    for c in rows:
        for d in (c.dimensions or []):
            dims[d if isinstance(d, str) else str(d)] += 1
    p0 = prio.get("P0", 0)
    print(f"batch {batch_id} | 用例 {n}")
    print(f"priority 分布: {dict(prio)}  | P0 占比 {p0/max(n,1)*100:.1f}%")
    print(f"维度标签种类数: {len(dims)}")
    print(f"非 enum/other 标签(若有): {[k for k in dims if k=='other']}")
    print("维度 top20:", dims.most_common(20))


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: 基线（旧批次）** — `uv run python scripts/metadata_regression.py 0c9b63e6-28cd-4efc-ae2e-0c9cbed9a9bb` → 记录 P0 占比 49.7% / 维度种类 ~98（改造前批次）。

- [ ] **Step 3: 新批次对比** — 重启 worker 后对同一 PRD 重新生成批次，跑本脚本 → 期望 P0<30% / 维度种类收敛到 ~30 + 极少 other。

- [ ] **Step 4: Commit**
```bash
git add scripts/metadata_regression.py
git commit -m "feat(test_points): 元数据回归脚本（priority 分布 + 维度种类对比）"
```

---

## Execution Handoff
Plan 完成。执行：Chunk 1 → 2 → 3 顺序；每 Task 走 TDD（红→绿→commit）；**提交隔离：只 add 本计划列出文件**。
执行后用 `metadata_regression.py` 出新旧对比，确认 P0<30% + 维度收敛。
