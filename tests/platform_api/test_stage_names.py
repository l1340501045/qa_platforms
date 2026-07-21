"""阶段名契约测试：内部节点名不能泄漏到平台进度契约。"""

from src.platform_api.api.v1.batches import _build_stage_progress
from src.platform_api.core.stage_names import (
    PIPELINE_STAGES,
    next_progress_stage_after_node,
    to_progress_canonical,
    to_progress_internal,
)


def test_internal_pipeline_nodes_map_to_public_progress_stages():
    """内部 LangGraph 节点必须归并到平台可展示的 7 个阶段。"""
    cases = {
        "parse": ("parse", "parse"),
        "comprehend": ("comprehend", "comprehend"),
        "rule_extract": ("gate", "gate"),
        "test_points": ("test_points", "test-points"),
        "write_cases": ("write_cases", "write-cases"),
        "review": ("review", "review-cases"),
        "backfill": ("review", "review-cases"),
        "verify": ("review", "review-cases"),
        "dedup": ("review", "review-cases"),
        "export": ("export", "export"),
    }

    for internal_stage, (stored_stage, public_stage) in cases.items():
        assert to_progress_internal(internal_stage) == stored_stage
        assert to_progress_canonical(internal_stage) == public_stage
        assert public_stage in PIPELINE_STAGES


def test_next_progress_stage_points_to_visible_running_stage():
    """节点完成后 current_stage 应前移到下一个用户可感知阶段。"""
    assert next_progress_stage_after_node("parse") == "comprehend"
    assert next_progress_stage_after_node("comprehend") == "gate"
    assert next_progress_stage_after_node("rule_extract") == "test_points"
    assert next_progress_stage_after_node("test_points") == "write_cases"
    assert next_progress_stage_after_node("write_cases") == "review"
    assert next_progress_stage_after_node("review") == "review"
    assert next_progress_stage_after_node("verify") == "review"
    assert next_progress_stage_after_node("dedup") == "export"
    assert next_progress_stage_after_node("export") == "export"


def test_suspended_batch_marks_gate_as_suspended():
    """NO_GO 挂起应显示在 Gate 阶段，而不是退回未开始。"""
    stages = _build_stage_progress("gate", "suspended")

    by_name = {stage["name"]: stage["status"] for stage in stages}
    assert by_name["parse"] == "completed"
    assert by_name["comprehend"] == "completed"
    assert by_name["gate"] == "suspended"
    assert by_name["test-points"] == "pending"
