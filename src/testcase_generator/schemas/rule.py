"""规则台账 schema。

- `ExtractedRule` / `UnitRules`：单个抽取单元的 LLM 输出（每单元一次调用产一批规则）。
- `RuleItem` / `RuleLedger`：汇总后的规则台账（统一编号 R-001.. + 回填来源模块）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ExtractedRule(BaseModel):
    """单条抽取规则（LLM 直接产出，尚未编号/未挂模块）。"""

    rule: str = Field(description="一条原子化、可验证的业务规则/验收标准（只讲一件事）")
    source_quote: str = Field(default="", description="该规则在 PRD 原文中的出处片段（短引用）")
    category: str = Field(default="", description="规则类型：功能/校验/权限/状态/边界/数据/联动 等")


class UnitRules(BaseModel):
    """单个模块单元抽取出的规则清单（LLM structured output schema）。"""

    rules: list[ExtractedRule] = Field(default_factory=list, description="本模块抽取出的业务规则清单")


class RuleItem(BaseModel):
    """规则台账条目（已统一编号、已回填来源模块）。"""

    rule_code: str = Field(default="", description="规则码，如 R-001（落库前编号；落库时映射为 uuid）")
    module: str = Field(description="来源模块标题")
    rule: str = Field(description="原子、可验证的业务规则")
    source_quote: str = Field(default="", description="PRD 原文出处片段")
    category: str = Field(default="", description="功能/校验/权限/状态/边界/数据/联动")


class RuleLedger(BaseModel):
    """整份 PRD 的规则台账。"""

    rules: list[RuleItem] = Field(default_factory=list)
    total: int = 0
    failed_units: int = 0
