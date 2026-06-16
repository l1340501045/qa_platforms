"""规则↔用例覆盖判定服务 —— 拿规则台账（应测清单）对照实际用例，逐条判定是否被真正覆盖。

固化自离线探针 `.qa_probe/rule_extract/compare.py`，关键强化（评审 M6）：
  - 判定 LLM 调用固定 `temperature=0`，使「规则覆盖率」红线可复现；
  - 召回关键词由规则自身（rule + category + source_quote）自动派生（CJK n-gram + 英文词），免手配；
  - 无相关候选用例时确定性判全未覆盖（省一次 LLM 调用）。

判定从严：仅当某用例确实「验证了该规则的具体条件/预期」才算覆盖；只是「涉及同一功能/字段
但没断言该规则行为」的不算覆盖（避免把灌水用例误判为有效覆盖）。

注意：本服务是离线探针/回归红线的【语义判定】口径，成本与不确定性较高；运行期覆盖闸用的是
【结构化集合判定】（规则有挂用例即覆盖），不调本服务——见 review 阶段。
"""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field

_CJK_RUN = re.compile(r"[\u4e00-\u9fff]{2,}")
_EN_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")


class RuleVerdict(BaseModel):
    rule_index: int = Field(description="规则序号（与输入 rules 列表一一对应，从 0 开始）")
    covered: bool = Field(description="该规则是否被候选用例中至少一条真正验证")
    covering_case_title: str = Field(default="", description="若覆盖，给出最匹配的用例标题")
    note: str = Field(default="", description="若未覆盖，简述缺什么")


class ModuleCoverage(BaseModel):
    verdicts: list[RuleVerdict] = Field(default_factory=list, description="对每条规则的覆盖判定")


_SYS = """角色：你是严格的测试评审专家。给你一批【应测业务规则清单】和现有系统生成的【候选测试用例】。
请逐条判定每条规则是否被候选用例真正覆盖。

判定标准（从严）：
- covered=true 仅当：候选用例中至少有一条**确实验证了该规则描述的具体条件与预期结果**。
- 下列情况一律判 covered=false：
  - 用例只涉及同一功能/同一字段，但没有断言该规则的具体行为或取值；
  - 用例预期是"PRD未定义/待确认/不做确定性断言"等占位；
  - 用例方向相关但遗漏了规则的关键约束（如规则要求"超1000行直接拒绝"，用例只测了正常导入）。
- 覆盖时在 covering_case_title 填最匹配的用例标题；未覆盖时在 note 简述缺口。

严格按 JSON Schema 输出，对输入每条规则都要给出一条 verdict。"""


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return " ".join(_as_text(v) for v in value)
    if isinstance(value, dict):
        return " ".join(_as_text(v) for v in value.values())
    return str(value)


def _case_blob(case: dict) -> str:
    return " ".join(
        _as_text(case.get(k))
        for k in ("title", "steps", "steps_brief", "expected_results", "expected", "dimensions")
    )


def _derive_keywords(rules: list[dict]) -> set[str]:
    """从规则文本自动派生召回关键词：CJK n-gram（短词整取 + 长词切 bigram）+ 英文词。"""
    kws: set[str] = set()
    for r in rules:
        text = f"{r.get('rule', '')} {r.get('category', '')} {r.get('source_quote', '')}"
        for run in _CJK_RUN.findall(text):
            if len(run) <= 4:
                kws.add(run)
            else:
                # 长短语切 2-gram，最大化召回（噪声仅影响排序，不影响判定）
                kws.update(run[i : i + 2] for i in range(len(run) - 1))
        for tok in _EN_TOKEN.findall(text):
            kws.add(tok.lower())
    return kws


def _score(case: dict, kws: set[str]) -> int:
    blob = _case_blob(case).lower()
    return sum(1 for k in kws if k.lower() in blob)


async def judge_rule_coverage(
    rules: list[dict], cases: list[dict], client, *, topk: int = 110
) -> dict:
    """判定一组规则被一组候选用例的覆盖情况。

    Returns:
        {total, covered, missed, miss_rate, detail:[{rule_code, rule, covered, covering_case, note}]}
    """
    if not rules:
        return {"total": 0, "covered": 0, "missed": 0, "miss_rate": 0.0, "detail": []}

    def _code(i: int, r: dict) -> str:
        return r.get("rule_code") or f"R-{i + 1:03d}"

    kws = _derive_keywords(rules)
    scored = [(c, _score(c, kws)) for c in cases]
    cand = [c for c, sc in sorted(scored, key=lambda x: -x[1]) if sc > 0][:topk]

    if not cand:
        detail = [
            {"rule_code": _code(i, r), "rule": r.get("rule", ""), "covered": False,
             "covering_case": "", "note": "无相关候选用例"}
            for i, r in enumerate(rules)
        ]
        return {"total": len(rules), "covered": 0, "missed": len(rules), "miss_rate": 1.0, "detail": detail}

    rules_in = [
        {"index": i, "rule": r.get("rule", ""), "category": r.get("category", ""),
         "source_quote": r.get("source_quote", "")}
        for i, r in enumerate(rules)
    ]
    cases_in = [
        {"title": _as_text(c.get("title")), "steps_brief": _as_text(c.get("steps") or c.get("steps_brief"))[:400],
         "expected": _as_text(c.get("expected_results") or c.get("expected"))[:160]}
        for c in cand
    ]
    user = json.dumps({"rules": rules_in, "candidate_cases": cases_in}, ensure_ascii=False)
    out: ModuleCoverage = await client.generate_structured(_SYS, user, ModuleCoverage, temperature=0.0)

    vmap = {v.rule_index: v for v in out.verdicts}
    detail = []
    covered = 0
    for i, r in enumerate(rules):
        v = vmap.get(i)
        cov = bool(v and v.covered)
        covered += int(cov)
        detail.append({
            "rule_code": _code(i, r),
            "rule": r.get("rule", ""),
            "covered": cov,
            "covering_case": (v.covering_case_title if v else ""),
            "note": (v.note if v and not cov else ""),
        })
    total = len(rules)
    return {
        "total": total,
        "covered": covered,
        "missed": total - covered,
        "miss_rate": round((total - covered) / total, 3),
        "detail": detail,
    }
