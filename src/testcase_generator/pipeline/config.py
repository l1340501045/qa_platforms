"""流水线运行期配置读取。

API 的 ``generation_config`` 是按批次传入的运行配置；全局 ``settings`` 是进程默认值。
这里统一做"批次配置优先、全局配置兜底"，避免前端/审计记录显示开关已开但节点实际仍读
全局默认值。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from src.platform_api.core.settings import settings
from src.testcase_generator.schemas.pipeline_state import PipelineState


@dataclass(frozen=True)
class PipelineSettings:
    """按批次覆盖的 settings 代理。"""

    generation_config: Mapping[str, Any]

    def __getattr__(self, name: str) -> Any:
        if name in self.generation_config:
            return self.generation_config[name]
        return getattr(settings, name)


def effective_settings(state: PipelineState | Mapping[str, Any]) -> PipelineSettings:
    """返回当前批次的有效配置视图。"""
    config = state.get("generation_config") or {}
    if not isinstance(config, Mapping):
        config = {}
    return PipelineSettings(config)


BEST_PRACTICE_GENERATION_CONFIG: dict[str, Any] = {
    "quality_profile": "best_practice_default_2026_07",
    "rule_extract_enabled": True,
    "rule_driven_testpoints_enabled": True,
    "rule_coverage_gate_enabled": True,
    "safe_dedup_enabled": True,
    "structural_coverage_enabled": True,
    "grounded_provenance_enabled": True,
    "verify_cross_section_conflict_enabled": True,
    "conflict_entity_gate_enabled": True,
    "oracle_guard_enabled": True,
    "verdict_reconcile_enabled": True,
    "conflict_revote_enabled": True,
    "revote_n": 3,
    "split_cap_enabled": True,
    "existence_merge_enabled": True,
    "cases_per_tp_cap": 4,
    "p0_quota_enabled": False,
    "p0_quota": 0.30,
}
