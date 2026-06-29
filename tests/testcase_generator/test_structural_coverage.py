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


import pytest


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
