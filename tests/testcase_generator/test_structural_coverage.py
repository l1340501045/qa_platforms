"""结构化覆盖单测。"""

from __future__ import annotations


def test_structural_schemas_parse():
    from src.testcase_generator.stages.test_points.structural.schemas import (
        Grant,
        PermissionMatrix,
        StateMachine,
        Transition,
    )

    pm = PermissionMatrix(
        roles=["管理员", "投手"],
        resources=["账户"],
        grants=[
            Grant(
                role="投手",
                resource="账户",
                operation="改他人",
                effect="deny",
                source_quote="投手不可改他人账户",
            )
        ],
    )
    assert pm.grants[0].effect == "deny"
    sm = StateMachine(
        name="任务",
        states=["待执行", "执行中"],
        transitions=[
            Transition(src="待执行", dst="执行中", event="开始", source_quote="点开始")
        ],
    )
    assert sm.transitions[0].dst == "执行中"


async def test_permission_extractor_parses(monkeypatch):
    from src.testcase_generator.stages.test_points.structural import (
        permission_extractor as pe,
    )
    from src.testcase_generator.stages.test_points.structural.schemas import (
        Grant,
        PermissionMatrix,
    )

    class _Fake:
        async def generate_structured(self, **kw):
            return PermissionMatrix(
                roles=["投手"],
                resources=["账户"],
                grants=[
                    Grant(
                        role="投手",
                        resource="账户",
                        operation="改他人",
                        effect="deny",
                        source_quote="q",
                    )
                ],
            )

    monkeypatch.setattr(pe, "get_llm_client", lambda: _Fake())
    pm = await pe.extract_permission_matrix("§10 权限：投手不可改他人账户")
    assert pm.grants[0].effect == "deny"


async def test_state_extractor_parses(monkeypatch):
    from src.testcase_generator.stages.test_points.structural import (
        state_extractor as se,
    )
    from src.testcase_generator.stages.test_points.structural.schemas import (
        StateMachine,
        Transition,
    )

    class _Fake:
        async def generate_structured(self, **kw):
            from src.testcase_generator.stages.test_points.structural.state_extractor import (
                _SMList,
            )

            return _SMList(
                machines=[
                    StateMachine(
                        name="任务",
                        states=["待执行", "执行中"],
                        transitions=[
                            Transition(
                                src="待执行", dst="执行中", event="开始", source_quote="q"
                            )
                        ],
                    )
                ]
            )

    monkeypatch.setattr(se, "get_llm_client", lambda: _Fake())
    sms = await se.extract_state_machines("§5.9 任务状态：待执行→执行中")
    assert len(sms) == 1
    assert sms[0].transitions[0].dst == "执行中"


async def test_permission_extractor_degrades_on_error(monkeypatch):
    from src.testcase_generator.stages.test_points.structural import (
        permission_extractor as pe,
    )

    class _Broken:
        async def generate_structured(self, **kw):
            raise RuntimeError("LLM down")

    monkeypatch.setattr(pe, "get_llm_client", lambda: _Broken())
    pm = await pe.extract_permission_matrix("anything")
    assert pm.grants == []


async def test_state_extractor_degrades_on_error(monkeypatch):
    from src.testcase_generator.stages.test_points.structural import (
        state_extractor as se,
    )

    class _Broken:
        async def generate_structured(self, **kw):
            raise RuntimeError("LLM down")

    monkeypatch.setattr(se, "get_llm_client", lambda: _Broken())
    sms = await se.extract_state_machines("anything")
    assert sms == []


def test_expand_permission_bounded():
    from src.testcase_generator.stages.test_points.structural.expander import (
        expand_permission,
    )
    from src.testcase_generator.stages.test_points.structural.schemas import (
        Grant,
        PermissionMatrix,
    )

    pm = PermissionMatrix(
        roles=["管理员", "投手"],
        resources=["账户"],
        grants=[
            Grant(
                role="投手",
                resource="账户",
                operation="改他人",
                effect="deny",
                source_quote="q",
            )
        ],
    )
    tps = expand_permission(pm, start_idx=0)
    assert all(t.structural_type == "permission" for t in tps)
    assert len({t.structural_key for t in tps}) == len(tps)


def test_expand_state_machine_bounded():
    from src.testcase_generator.stages.test_points.structural.expander import (
        expand_state_machine,
    )
    from src.testcase_generator.stages.test_points.structural.schemas import (
        StateMachine,
        Transition,
    )

    sm = StateMachine(
        name="任务",
        states=["待执行", "执行中", "完成"],
        transitions=[
            Transition(src="待执行", dst="执行中", event="开始", source_quote="q"),
            Transition(src="执行中", dst="完成", event="结束", source_quote="q"),
        ],
    )
    tps = expand_state_machine(sm, start_idx=0)
    assert sum(1 for t in tps if "->" in (t.structural_key or "")) >= 2


def test_expand_permission_feature_mapping():
    """结构化点应映射到含相关资源名的 feature，而非 STRUCTURAL。"""
    from src.testcase_generator.schemas.parsed_context import FeatureItem
    from src.testcase_generator.stages.test_points.structural.expander import (
        expand_permission,
    )
    from src.testcase_generator.stages.test_points.structural.schemas import (
        Grant,
        PermissionMatrix,
    )

    pm = PermissionMatrix(
        roles=["投手"],
        resources=["账户"],
        grants=[
            Grant(role="投手", resource="账户", operation="改他人", effect="deny", source_quote="q")
        ],
    )
    features = [
        FeatureItem(id="F-001", name="账户管理", description="管理账户信息"),
        FeatureItem(id="F-002", name="商品列表", description="展示商品"),
    ]
    tps = expand_permission(pm, start_idx=0, features=features)
    assert all(t.feature_id == "F-001" for t in tps)


def test_compute_structural_coverage():
    from src.testcase_generator.schemas.test_point import TestPointSchema
    from src.testcase_generator.stages.review.rule_gate import (
        compute_structural_coverage,
    )

    tps = [
        TestPointSchema(
            id="TP-001",
            feature_id="S",
            dimension="access_control",
            description="x",
            priority="P0",
            structural_type="permission",
            structural_key="perm:投手:账户:改他人",
        )
    ]
    cov = compute_structural_coverage(tps, covered_tp_ids={"TP-001"})
    assert cov["structural_total"] == 1 and cov["structural_covered"] == 1
    cov2 = compute_structural_coverage(tps, covered_tp_ids=set())
    assert cov2["structural_covered"] == 0
    assert "perm:投手:账户:改他人" in cov2["uncovered_structural_keys"]


def test_audit_report_has_structural_fields():
    from src.testcase_generator.schemas.audit_report import AuditReport

    ar = AuditReport(
        total_test_points=1,
        per_test_point_covered=1,
        dimension_cell_total=1,
        dimension_cell_covered=1,
        dimension_cell_coverage=1.0,
    )
    assert ar.structural_total == 0
    assert ar.structural_coverage == 1.0


def test_test_point_has_structural_fields():
    from src.testcase_generator.schemas.test_point import TestPointSchema

    tp = TestPointSchema(
        id="TP-001",
        feature_id="F1",
        dimension="access_control",
        description="x",
        priority="P0",
        structural_type="permission",
        structural_key="perm:投手:账户:改他人",
    )
    assert tp.structural_type == "permission"
    assert (
        TestPointSchema(
            id="T", feature_id="F", dimension="d", description="x", priority="P2"
        ).structural_type
        is None
    )
