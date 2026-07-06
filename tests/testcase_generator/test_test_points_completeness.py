"""测试 test_points 完整性兜底：批失败重试 + 单 feature 降级 + 缺额校验。

根因：_BATCH_MAX_FEATURES=4 分批后，某批 LLM 调用异常返回 None → 该批所有
feature 零测试点、仅打 error log、无完整性校验、无重试 → 9 feature 静默丢失。

修复行为（test_points_completeness_guard=True）：
1. 失败批整批重试 1 次（temperature 微调 0.3→0.5）
2. 重试仍失败 → 拆成单 feature 逐个调用（最大保全）
3. 全部生成后做完整性校验：missing_feature_ids 记入 state + WARN
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.testcase_generator.stages.test_points import node as tp_node
from src.testcase_generator.stages.test_points.node import (
    GeneratedTestPoint,
    TestPointsLLMOutput,
    _generate_test_points_batched,
    _pack_feature_batches,
)


def _feature(fid: str, desc_len: int = 50) -> dict:
    return {
        "feature_id": fid,
        "feature_name": f"功能{fid}",
        "feature_description": "x" * desc_len,
        "source_refs": ["PRD §1"],
        "applicable_dimensions": [{"name": "functional_correctness"}],
    }


def _tp(fid: str) -> GeneratedTestPoint:
    return GeneratedTestPoint(
        feature_id=fid,
        dimension="functional_correctness",
        description="具体测试点",
        priority="P0",
        derived_from=["PRD §1"],
    )


class TestCompletenessGuardRetry:
    """guard 开时：失败批重试 + 单 feature 降级"""

    @pytest.mark.asyncio
    async def test_failed_batch_retried_then_single_feature_fallback(self):
        """5 features → 2 批 (4+1)；第 2 批始终失败 → 拆单 feature 重试 → 全覆盖"""
        feats = [_feature(f"F-{i:03d}") for i in range(5)]
        batches = _pack_feature_batches(feats)
        assert len(batches) == 2, "5 features should split into 2 batches (4+1)"

        call_count = {"n": 0}

        async def selective_fail(*, system_prompt, user_content, output_schema, temperature):
            call_count["n"] += 1
            payload = json.loads(user_content)
            fids = [f["feature_id"] for f in payload["features_with_dimensions"]]

            # 第 2 批（含 F-004）在整批调用时始终失败；单 feature 调用时成功
            if len(fids) > 1 and "F-004" in fids:
                raise RuntimeError("网关 504")
            # 单 feature 调用 + 第 1 批正常
            return TestPointsLLMOutput(test_points=[_tp(fid) for fid in fids])

        fake_client = AsyncMock()
        fake_client.generate_structured = AsyncMock(side_effect=selective_fail)

        with (
            patch.object(tp_node, "get_llm_client", return_value=fake_client),
            patch.object(tp_node.settings, "test_points_completeness_guard", True),
        ):
            result = await _generate_test_points_batched(feats, shared_context=[])

        covered_fids = {tp.feature_id for tp in result}
        assert len(covered_fids) == 5, (
            f"All 5 features must have test points, got {covered_fids}"
        )

    @pytest.mark.asyncio
    async def test_retry_uses_different_temperature(self):
        """重试时 temperature 应微调（0.3→0.5），避免相同输入触发相同失败"""
        feats = [_feature(f"F-{i:03d}") for i in range(5)]
        temperatures_seen = []

        async def record_temp(*, system_prompt, user_content, output_schema, temperature):
            temperatures_seen.append(temperature)
            payload = json.loads(user_content)
            fids = [f["feature_id"] for f in payload["features_with_dimensions"]]
            if len(temperatures_seen) <= 2:
                # 前两次调用（首次 batch 2 + 重试）失败
                if "F-004" in fids:
                    raise RuntimeError("网关 504")
            return TestPointsLLMOutput(test_points=[_tp(fid) for fid in fids])

        fake_client = AsyncMock()
        fake_client.generate_structured = AsyncMock(side_effect=record_temp)

        with (
            patch.object(tp_node, "get_llm_client", return_value=fake_client),
            patch.object(tp_node.settings, "test_points_completeness_guard", True),
        ):
            await _generate_test_points_batched(feats, shared_context=[])

        # 重试时应有不同于 0.3 的 temperature
        assert any(t != 0.3 for t in temperatures_seen), (
            f"Retry should use different temperature, saw: {temperatures_seen}"
        )


class TestCompletenessGuardOff:
    """guard 关时：退回旧行为（失败批静默丢）"""

    @pytest.mark.asyncio
    async def test_guard_off_preserves_old_behavior_silent_drop(self):
        """guard 关 → 第 2 批失败 → 对应 feature 静默丢失（复现 bug）"""
        feats = [_feature(f"F-{i:03d}") for i in range(5)]
        call_count = {"n": 0}

        async def fail_second_batch(*, system_prompt, user_content, output_schema, temperature):
            call_count["n"] += 1
            payload = json.loads(user_content)
            fids = [f["feature_id"] for f in payload["features_with_dimensions"]]
            if "F-004" in fids:
                raise RuntimeError("网关 504")
            return TestPointsLLMOutput(test_points=[_tp(fid) for fid in fids])

        fake_client = AsyncMock()
        fake_client.generate_structured = AsyncMock(side_effect=fail_second_batch)

        with (
            patch.object(tp_node, "get_llm_client", return_value=fake_client),
            patch.object(tp_node.settings, "test_points_completeness_guard", False),
        ):
            result = await _generate_test_points_batched(feats, shared_context=[])

        covered_fids = {tp.feature_id for tp in result}
        # guard 关 → 第 2 批丢失，只有前 4 个 feature 有测试点
        assert "F-004" not in covered_fids
        assert len(covered_fids) == 4


class TestCompletenessCheck:
    """完整性校验：生成后检测 missing_feature_ids"""

    @pytest.mark.asyncio
    async def test_missing_features_tracked_in_return(self):
        """即使重试+降级仍有 feature 完全失败 → 返回中标记 missing"""
        feats = [_feature(f"F-{i:03d}") for i in range(5)]

        async def always_fail_f004(*, system_prompt, user_content, output_schema, temperature):
            payload = json.loads(user_content)
            fids = [f["feature_id"] for f in payload["features_with_dimensions"]]
            # F-004 无论整批还是单独都失败
            if "F-004" in fids:
                raise RuntimeError("F-004 永远失败")
            return TestPointsLLMOutput(test_points=[_tp(fid) for fid in fids])

        fake_client = AsyncMock()
        fake_client.generate_structured = AsyncMock(side_effect=always_fail_f004)

        with (
            patch.object(tp_node, "get_llm_client", return_value=fake_client),
            patch.object(tp_node.settings, "test_points_completeness_guard", True),
        ):
            result = await _generate_test_points_batched(feats, shared_context=[])

        # 应返回 4 个 feature 的测试点（F-004 彻底失败）
        covered_fids = {tp.feature_id for tp in result}
        assert "F-004" not in covered_fids
        assert len(covered_fids) == 4

    @pytest.mark.asyncio
    async def test_all_features_covered_returns_empty_missing(self):
        """全部成功 → 无 missing"""
        feats = [_feature(f"F-{i:03d}") for i in range(5)]

        async def always_ok(*, system_prompt, user_content, output_schema, temperature):
            payload = json.loads(user_content)
            fids = [f["feature_id"] for f in payload["features_with_dimensions"]]
            return TestPointsLLMOutput(test_points=[_tp(fid) for fid in fids])

        fake_client = AsyncMock()
        fake_client.generate_structured = AsyncMock(side_effect=always_ok)

        with (
            patch.object(tp_node, "get_llm_client", return_value=fake_client),
            patch.object(tp_node.settings, "test_points_completeness_guard", True),
        ):
            result = await _generate_test_points_batched(feats, shared_context=[])

        covered_fids = {tp.feature_id for tp in result}
        assert len(covered_fids) == 5
