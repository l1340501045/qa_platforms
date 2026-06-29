"""权限矩阵/状态机 → 有界展开成 TestPointSchema（带 structural_type/key）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.testcase_generator.schemas.test_point import TestPointSchema
from src.testcase_generator.stages.test_points.structural.schemas import (
    PermissionMatrix,
    StateMachine,
)

if TYPE_CHECKING:
    from src.testcase_generator.schemas.parsed_context import FeatureItem


def _match_feature(hint: str, features: list[FeatureItem]) -> str:
    """按 hint 模糊匹配 feature，命中返回 feature.id，否则回退第一个 feature。"""
    if not features:
        return "STRUCTURAL"
    for f in features:
        if hint in f.name or hint in f.description:
            return f.id
    return features[0].id


def _tp(
    idx: int, dim: str, desc: str, key: str, stype: str, quote: str, feature_id: str
) -> TestPointSchema:
    return TestPointSchema(
        id=f"TP-{idx:03d}",
        feature_id=feature_id,
        dimension=dim,
        description=desc,
        priority="P0",
        derived_from=[quote] if quote else [],
        structural_type=stype,
        structural_key=key,
    )


def expand_permission(
    pm: PermissionMatrix,
    start_idx: int,
    features: list[FeatureItem] | None = None,
) -> list[TestPointSchema]:
    features = features or []
    out: list[TestPointSchema] = []
    seen: set[str] = set()
    i = start_idx
    for g in pm.grants:
        key = f"perm:{g.role}:{g.resource}:{g.operation}"
        if key in seen:
            continue
        seen.add(key)
        i += 1
        verb = "应被拒绝" if g.effect == "deny" else "应被允许"
        fid = _match_feature(g.resource, features)
        out.append(
            _tp(
                i,
                "access_control",
                f"{g.role} 对「{g.resource}」执行「{g.operation}」{verb}",
                key,
                "permission",
                g.source_quote,
                fid,
            )
        )
    for res in pm.resources:
        allow_roles = [
            g.role for g in pm.grants if g.resource == res and g.effect == "allow"
        ]
        deny_roles = [
            g.role for g in pm.grants if g.resource == res and g.effect == "deny"
        ]
        for label, roles, verb in (
            ("有权", allow_roles, "应被允许"),
            ("无权", deny_roles, "应被拒绝"),
        ):
            if roles:
                key = f"perm:{label}:{res}"
                if key not in seen:
                    seen.add(key)
                    i += 1
                    fid = _match_feature(res, features)
                    out.append(
                        _tp(
                            i,
                            "access_control",
                            f"{label}角色（{roles[0]}）访问「{res}」{verb}（等价类代表）",
                            key,
                            "permission",
                            "",
                            fid,
                        )
                    )
    return out


def expand_state_machine(
    sm: StateMachine,
    start_idx: int,
    features: list[FeatureItem] | None = None,
) -> list[TestPointSchema]:
    features = features or []
    out: list[TestPointSchema] = []
    i = start_idx
    fid = _match_feature(sm.name, features)
    terminal = {s for s in sm.states if not any(t.src == s for t in sm.transitions)}
    for t in sm.transitions:
        i += 1
        key = f"state:{sm.name}:{t.src}->{t.dst}"
        desc = f"{sm.name}：在「{t.src}」触发「{t.event}」应转移到「{t.dst}」"
        if t.guard:
            desc += f"（守卫：{t.guard}）"
        out.append(_tp(i, "state_transition", desc, key, "state_machine", t.source_quote, fid))
    events = sorted({t.event for t in sm.transitions if t.event})
    for s in sorted(terminal):
        if events:
            i += 1
            key = f"state:{sm.name}:{s}->illegal"
            out.append(
                _tp(
                    i,
                    "state_transition",
                    f"{sm.name}：终态「{s}」后再触发「{events[0]}」应被拒绝/无效（非法转移）",
                    key,
                    "state_machine",
                    "",
                    fid,
                )
            )
    return out
