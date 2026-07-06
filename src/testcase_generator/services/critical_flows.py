"""关键业务流目录。

该目录是生成侧锚点与审计侧覆盖统计的单一来源，避免“报告知道主链路，生成阶段不知道”
导致下一批仍然漏主流程。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CriticalFlowSpec:
    """一条需要被显式覆盖的关键业务流。"""

    key: str
    source_tokens: tuple[str, ...]
    title: str
    description: str


CRITICAL_FLOW_SPECS: tuple[CriticalFlowSpec, ...] = (
    CriticalFlowSpec(
        key="account_auth_pull",
        source_tokens=("§5.1.6",),
        title="账户授权底层拉取",
        description="覆盖授权账户拉取、异常返回、任务或数据回写的可观测闭环。",
    ),
    CriticalFlowSpec(
        key="batch_submit",
        source_tokens=("§5.8.13",),
        title="批量提交",
        description="覆盖从账户、素材、标题、商品、定向、链接到提交审核与任务创建的主链路。",
    ),
    CriticalFlowSpec(
        key="submit_result_state",
        source_tokens=("§5.8.13.1",),
        title="提交结果状态",
        description="覆盖成功、失败、部分失败状态回写，以及任务中心或结果页的可追踪展示。",
    ),
    CriticalFlowSpec(
        key="task_state",
        source_tokens=("§5.9.3", "§5.9.4"),
        title="任务中心状态",
        description="覆盖任务状态流转、查看失败原因、重试或取消后的状态一致性。",
    ),
    CriticalFlowSpec(
        key="monitoring_binding",
        source_tokens=("§7.2",),
        title="监测链接绑定",
        description="覆盖按投放方式自动绑定预置监测链接，并校验提交 payload 与页面展示一致。",
    ),
    CriticalFlowSpec(
        key="monitoring_source",
        source_tokens=("§7.1",),
        title="监测链接来源",
        description="覆盖预置链接来源、宏参数映射、缺失或过期时的拦截与提示。",
    ),
    CriticalFlowSpec(
        key="submit_limit",
        source_tokens=("§8.4",),
        title="批量提交防超限",
        description="覆盖提交限流、幂等、防重复、失败重试与恢复后的数据一致性。",
    ),
    CriticalFlowSpec(
        key="event_asset",
        source_tokens=("§8.2", "§8.3"),
        title="事件资产",
        description="覆盖优化目标对应事件资产的检测、创建、映射失败恢复与提交前校验。",
    ),
)

CRITICAL_FLOW_PATTERNS: dict[str, tuple[str, ...]] = {spec.key: spec.source_tokens for spec in CRITICAL_FLOW_SPECS}


def source_ref_matches_token(source_ref: str, token: str) -> bool:
    """匹配 source_ref 中的章节 token，避免 `§5.8.13` 误命中 `§5.8.13.1`。"""
    start = source_ref.find(token)
    if start < 0:
        return False
    end = start + len(token)
    if end >= len(source_ref):
        return True
    return source_ref[end] not in ".0123456789"


def matching_critical_flow_specs(source_refs: list[str]) -> list[CriticalFlowSpec]:
    """返回与 source_refs 命中的关键业务流，按目录稳定排序。"""
    refs = [str(ref) for ref in source_refs if ref]
    return [
        spec
        for spec in CRITICAL_FLOW_SPECS
        if any(source_ref_matches_token(ref, token) for ref in refs for token in spec.source_tokens)
    ]
