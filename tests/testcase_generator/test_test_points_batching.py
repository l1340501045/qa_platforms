"""回归测试：test-points 阶段必须按功能点分批并发调用，且失败隔离。

根因背景：原实现把全部功能点塞进单次 LLM 调用，大型 PRD（如 127 功能点）
导致输出超限、网关返回空、重试耗尽 → 阶段失败。改为分批后：
- 多批并发，每批受字符数 + 功能点数双上限约束；
- 部分批失败时保留其余批结果（不整段失败）；
- 全部批失败才抛错。
"""

from unittest.mock import AsyncMock, patch

import pytest

from src.testcase_generator.stages.test_points import node as tp_node
from src.testcase_generator.stages.test_points.node import (
    GeneratedTestPoint,
    TestPointsLLMOutput,
    _pack_feature_batches,
    _generate_test_points_batched,
)


def _feature(fid: str, desc_len: int = 50) -> dict:
    return {
        "feature_id": fid,
        "feature_name": f"功能{fid}",
        "feature_description": "x" * desc_len,
        "source_refs": ["PRD §1"],
        "applicable_dimensions": [{"name": "functional_completeness"}],
    }


def _tp(fid: str) -> GeneratedTestPoint:
    return GeneratedTestPoint(
        feature_id=fid, dimension="functional_completeness",
        description="具体测试点", priority="P0", derived_from=["PRD §1"],
    )


def test_pack_batches_respects_feature_count_cap():
    feats = [_feature(f"F{i}") for i in range(30)]
    batches = _pack_feature_batches(feats)
    assert len(batches) >= 3  # 30 / 12 → 至少 3 批
    assert all(len(b) <= 12 for b in batches)
    assert sum(len(b) for b in batches) == 30  # 不丢功能点


def test_pack_batches_respects_char_limit():
    # 单个功能点就很大 → 每批最多装下有限个
    feats = [_feature(f"F{i}", desc_len=30000) for i in range(5)]
    batches = _pack_feature_batches(feats)
    assert len(batches) == 5  # 每批 1 个（超字符上限）
    assert sum(len(b) for b in batches) == 5


@pytest.mark.asyncio
async def test_batched_generation_aggregates_all_batches():
    feats = [_feature(f"F{i}") for i in range(25)]

    async def fake_structured(*, system_prompt, user_content, output_schema, temperature):
        import json
        payload = json.loads(user_content)
        fids = [f["feature_id"] for f in payload["features_with_dimensions"]]
        return TestPointsLLMOutput(test_points=[_tp(fid) for fid in fids])

    fake_client = AsyncMock()
    fake_client.generate_structured = AsyncMock(side_effect=fake_structured)
    with patch.object(tp_node, "get_llm_client", return_value=fake_client):
        result = await _generate_test_points_batched(feats, shared_context=[])

    assert len(result) == 25  # 每个功能点一个测试点，全部聚合


@pytest.mark.asyncio
async def test_partial_batch_failure_keeps_successes():
    feats = [_feature(f"F{i}") for i in range(24)]
    batches = _pack_feature_batches(feats)
    assert len(batches) >= 2  # 需要多批才能验证"部分失败"
    first_batch_size = len(batches[0])
    calls = {"n": 0}

    async def flaky(*, system_prompt, user_content, output_schema, temperature):
        import json
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("网关返回空")  # 第一批失败
        payload = json.loads(user_content)
        fids = [f["feature_id"] for f in payload["features_with_dimensions"]]
        return TestPointsLLMOutput(test_points=[_tp(fid) for fid in fids])

    fake_client = AsyncMock()
    fake_client.generate_structured = AsyncMock(side_effect=flaky)
    with (
        patch.object(tp_node, "get_llm_client", return_value=fake_client),
        patch.object(tp_node.settings, "test_points_completeness_guard", False),
    ):
        result = await _generate_test_points_batched(feats, shared_context=[])

    # guard 关：仅第一批失败，其余批结果应全部保留（与批大小无关）
    assert len(result) == 24 - first_batch_size


@pytest.mark.asyncio
async def test_all_batches_failed_raises():
    feats = [_feature(f"F{i}") for i in range(5)]

    fake_client = AsyncMock()
    fake_client.generate_structured = AsyncMock(side_effect=RuntimeError("全挂"))
    with patch.object(tp_node, "get_llm_client", return_value=fake_client):
        with pytest.raises(RuntimeError, match="全部"):
            await _generate_test_points_batched(feats, shared_context=[])


# ── 根因3：质量属性维度信号门控 ────────────────────────────────────────────────

def _dim(name: str) -> dict:
    return {"name": name}


def test_quality_dimensions_gated_when_prd_silent():
    # 纯权限 PRD：未提性能/注入/接口契约 → 这些质量属性维度被门控；功能/权限维度保留
    dims = [
        _dim("functional_correctness"),
        _dim("access_control"),
        _dim("permission_denied"),
        _dim("response_time"),
        _dim("input_injection"),
        _dim("api_contract"),
        _dim("large_data_volume"),
    ]
    feature_text = "CP书籍数据权限控制：非超管仅能查看本人负责的CP商选书数据"
    kept = {d["name"] for d in tp_node._gate_quality_dimensions(dims, feature_text, "")}
    assert {"functional_correctness", "access_control", "permission_denied"} <= kept
    assert "response_time" not in kept
    assert "input_injection" not in kept
    assert "api_contract" not in kept
    assert "large_data_volume" not in kept


def test_quality_dimensions_kept_when_signal_present():
    dims = [_dim("response_time"), _dim("api_contract"), _dim("pagination_boundary")]
    feature_text = "列表加载时间需小于2秒；分页每页20条；调用接口返回状态码与响应结构需符合契约"
    kept = {d["name"] for d in tp_node._gate_quality_dimensions(dims, feature_text, "")}
    assert kept == {"response_time", "api_contract", "pagination_boundary"}


def test_gate_uses_global_signal_text():
    # 功能点自身没提状态机，但技术文档(全局)定义了 → 放行，避免漏测技术方案维度
    dims = [_dim("state_transition")]
    global_text = "技术方案：任务状态机 草稿->提交->审核->驳回 的状态流转校验".lower()
    kept = {d["name"] for d in tp_node._gate_quality_dimensions(dims, "提交任务", global_text)}
    assert "state_transition" in kept


def test_field_name_does_not_falsely_trigger_api_gate():
    # "接口标识"是字段名，不应让 api_contract 维度被误放行(信号用具体词组而非裸"接口")
    dims = [_dim("api_contract")]
    feature_text = "列表移除【appid】【密钥】【接口标识】字段"
    kept = {d["name"] for d in tp_node._gate_quality_dimensions(dims, feature_text, "")}
    assert "api_contract" not in kept
