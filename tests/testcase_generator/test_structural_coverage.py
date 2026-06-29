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
