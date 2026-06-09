"""T028: 可信度标注 — 基于信源信任等级派生，不靠 AI 自评"""

from __future__ import annotations

from pathlib import Path

import yaml

from src.testcase_generator.schemas.test_case import Provenance


_TRUST_ORDER_PATH = Path(__file__).resolve().parents[2] / "config" / "trust_order.yaml"


def _load_confidence_rules() -> dict:
    """加载 trust_order.yaml 中的 confidence_rules"""
    with open(_TRUST_ORDER_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("confidence_rules", {})


class ConfidenceScorer:
    """可信度标注 — 基于信源信任等级派生，不靠 AI 自评

    规则（从 trust_order.yaml confidence_rules 读取）：
    - trust_level 1-2: 高可信，note=None
    - trust_level 3: 中可信，note=None
    - trust_level 4: 中可信，note="来源为 UI 设计稿，建议人工确认交互细节"
    - trust_level 5: 低可信，note="来源含原型探索，原型可能有交互 bug"
    """

    def __init__(self) -> None:
        self._rules = _load_confidence_rules()

    def score(self, provenance: Provenance) -> tuple[int, str | None]:
        """返回 (trust_level, confidence_note)

        trust_level 直接取 provenance.trust_level（已按硬约束#5仲裁）。
        confidence_note 根据规则派生。
        """
        level = provenance.trust_level

        if level <= 2:
            return level, None
        elif level == 3:
            return level, None
        elif level == 4:
            return level, "来源为 UI 设计稿，建议人工确认交互细节"
        else:  # level == 5
            return level, "来源含原型探索，原型可能有交互 bug"
