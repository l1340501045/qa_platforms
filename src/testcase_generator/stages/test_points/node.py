"""T023: test-points 节点 — LLM 生成具体测试点 + 维度矩阵裁剪"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import List, Literal, cast

import yaml
from pydantic import BaseModel, Field

from src.platform_api.core.settings import settings
from src.testcase_generator.schemas.pipeline_state import PipelineState
from src.testcase_generator.schemas.test_point import TestPointSchema
from src.testcase_generator.stages.test_points.applicability_filter import (
    ApplicabilityFilter,
)
from src.testcase_generator.stages.test_points.mandatory_dimensions import (
    MandatoryDimensionInjector,
)
from src.testcase_generator.services.llm_client import get_llm_client

logger = logging.getLogger(__name__)

_DIMENSIONS_PATH = Path(__file__).resolve().parents[2] / "config" / "dimensions.yaml"


# ─── LLM 输出 Schema ──────────────────────────────────────────────────────────


class GeneratedTestPoint(BaseModel):
    """LLM 生成的单个测试点"""

    feature_id: str = Field(description="关联功能 ID")
    dimension: str = Field(description="维度名称")
    description: str = Field(description="具体、可验证的测试点描述")
    priority: str = Field(description="优先级 P0/P1/P2/P3")
    derived_from: List[str] = Field(default_factory=list, description="来源引用")


class TestPointsLLMOutput(BaseModel):
    """LLM 测试点生成的完整输出"""

    test_points: List[GeneratedTestPoint] = Field(description="生成的测试点列表")


# ─── Prompt ────────────────────────────────────────────────────────────────────

TEST_POINTS_SYSTEM_PROMPT = """角色：你是资深测试工程师，当前任务是为每个功能点设计具体的测试点。

方法论约束：
- 维度驱动：每个功能点只覆盖已通过适用性裁剪的维度（输入中已标明每个功能点的适用维度列表）
- 详尽优先：不设数量上限，每个维度至少一个测试点，复杂维度应有多个测试点
- 每个测试点必须具体、可验证，不能是抽象描述
  - 好例子："用户名输入超过50个字符时，系统应提示'用户名长度不能超过50个字符'"
  - 坏例子："验证用户名边界值"
- 测试点应覆盖正常路径和异常路径
- priority 判定：
  - P0: 核心功能路径、安全相关、数据完整性
  - P1: 边界条件、错误处理、状态转换
  - P2: 性能、兼容性、可用性
  - P3: 极端边缘场景

输入格式：包含功能点列表（每个带适用维度和维度 check_points）+ 需求上下文摘要。

输出要求：严格按指定 JSON Schema 输出。每个测试点的 description 必须具体到可以直接编写测试用例。"""


# ─── Helper Functions ──────────────────────────────────────────────────────────


def _load_dimensions() -> list[dict]:
    """加载 dimensions.yaml 中的全部维度定义"""
    with open(_DIMENSIONS_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("dimensions", [])


def _infer_feature_types(feature) -> list[str]:
    """从功能点元数据推断 feature_types 列表"""
    types: set[str] = set()

    if feature.feature_type and feature.feature_type != "general":
        types.add(feature.feature_type)

    desc = f"{feature.name} {feature.description}".lower()
    keyword_map = {
        "表单": "form",
        "输入": "data_input",
        "列表": "list",
        "搜索": "search",
        "上传": "file_upload",
        "导入": "import",
        "导出": "export",
        "支付": "payment",
        "订单": "order",
        "审批": "workflow",
        "流程": "workflow",
        "接口": "api",
        "api": "api_call",
        "登录": "login",
        "权限": "multi_role",
        "统计": "report",
        "报表": "report",
        "计算": "calculation",
        "配置": "configuration",
        "设置": "settings",
        "通知": "notification",
        "消息": "message_queue",
    }
    for keyword, ftype in keyword_map.items():
        if keyword in desc:
            types.add(ftype)

    if not types:
        types.add("general")

    return list(types)


def _derive_priority(dim: dict) -> str:
    """根据维度分类派生默认优先级"""
    category = dim.get("category", "")
    priority_map = {
        "functional": "P0",
        "boundary": "P1",
        "error": "P1",
        "security": "P0",
        "performance": "P2",
        "usability": "P2",
        "data": "P1",
        "state": "P1",
        "integration": "P2",
    }
    return priority_map.get(category, "P2")


# ─── 分批生成 ────────────────────────────────────────────────────────────────────

# 单批输入字符预估上限与功能点数上限。双上限确保「输入不超长」且「输出测试点数量可控」。
# 实测自建网关单请求 >~260s 会 504，故批切小（更快返回、稳落在网关超时内），
# 用"更多更小调用"换稳定全覆盖（符合质量/覆盖 > 时间的取向）。
_BATCH_CHAR_LIMIT = 15000
_BATCH_MAX_FEATURES = 4


def _pack_feature_batches(feature_dim_inputs: list[dict]) -> list[list[dict]]:
    """把功能点按字符预估 + 数量双上限打包成多批"""
    batches: list[list[dict]] = []
    cur: list[dict] = []
    cur_chars = 0
    for fi in feature_dim_inputs:
        fchars = len(json.dumps(fi, ensure_ascii=False))
        if cur and (len(cur) >= _BATCH_MAX_FEATURES or cur_chars + fchars > _BATCH_CHAR_LIMIT):
            batches.append(cur)
            cur, cur_chars = [], 0
        cur.append(fi)
        cur_chars += fchars
    if cur:
        batches.append(cur)
    return batches


async def _generate_test_points_batched(
    feature_dim_inputs: list[dict],
    shared_context: list[dict],
) -> list[GeneratedTestPoint]:
    """分批并发调用 LLM 生成测试点；失败的批跳过并记录，全部失败才抛错"""
    if not feature_dim_inputs:
        return []

    batches = _pack_feature_batches(feature_dim_inputs)
    semaphore = asyncio.Semaphore(settings.llm_concurrency)

    async def _call_batch(batch_idx: int, feats: list[dict]) -> list[GeneratedTestPoint] | None:
        async with semaphore:
            user_content = json.dumps(
                {"features_with_dimensions": feats, "requirement_context": shared_context},
                ensure_ascii=False,
                indent=2,
            )
            try:
                out = await get_llm_client().generate_structured(
                    system_prompt=TEST_POINTS_SYSTEM_PROMPT,
                    user_content=user_content,
                    output_schema=TestPointsLLMOutput,
                    temperature=0.3,
                )
                return out.test_points
            except Exception as e:  # noqa: BLE001 — 单批失败不拖垮整阶段
                logger.error(
                    "test-points 批次失败 batch=%d/%d feats=%s: %s",
                    batch_idx + 1,
                    len(batches),
                    [f["feature_id"] for f in feats],
                    e,
                )
                return None

    logger.info("test-points: %d 个功能点拆成 %d 批并发, 并发度=%d", len(feature_dim_inputs), len(batches), settings.llm_concurrency)
    results = await asyncio.gather(*[_call_batch(i, b) for i, b in enumerate(batches)])

    generated: list[GeneratedTestPoint] = []
    failed = 0
    for r in results:
        if r is None:
            failed += 1
        else:
            generated.extend(r)

    if failed == len(batches):
        raise RuntimeError(f"test-points 全部 {len(batches)} 批均失败，无法生成测试点")
    if failed:
        logger.warning("test-points: %d/%d 批失败，已保留其余批结果", failed, len(batches))

    return generated


# ─── Node ──────────────────────────────────────────────────────────────────────


async def test_points_node(state: PipelineState) -> dict:
    """Stage 3: 维度矩阵裁剪 + LLM 生成具体测试点 + 漏测强制注入

    硬约束#4: 走适用性矩阵裁剪 + 漏测 Bug 强制维度注入，不无脑全套 43 维度
    改进：测试点的具体描述由 LLM 生成，而非硬编码模板。
    """
    parsed_context = state["parsed_context"]
    all_dimensions = _load_dimensions()

    applicability_filter = ApplicabilityFilter()

    # 1. 为每个功能点进行适用性裁剪，构建 LLM 输入
    feature_dim_inputs = []
    for feature in parsed_context.features:
        feature_types = _infer_feature_types(feature)
        applicable_dims = applicability_filter.filter_dimensions(feature_types, all_dimensions)

        dims_info = []
        for dim in applicable_dims:
            dims_info.append(
                {
                    "name": dim["name"],
                    "description": dim.get("description", ""),
                    "category": dim.get("category", ""),
                    "check_points": dim.get("check_points", []),
                    "default_priority": _derive_priority(dim),
                }
            )

        feature_dim_inputs.append(
            {
                "feature_id": feature.id,
                "feature_name": feature.name,
                "feature_description": feature.description,
                "source_refs": feature.source_refs,
                "applicable_dimensions": dims_info,
            }
        )

    # 2. 组装需求上下文摘要
    context_summary = []
    for source in parsed_context.sources:
        for section in source.sections:
            context_summary.append(
                {
                    "source": source.title,
                    "trust_level": source.trust_level,
                    "heading": section.heading,
                    "content": section.content[:300],
                }
            )

    shared_context = context_summary[:20]  # 限制上下文长度，各批共享

    # 3. 按功能点打包分批并发调用 LLM 生成测试点
    #    单次塞入全部功能点会导致超大输出 → 网关返回空 → 重试耗尽阶段失败。
    #    故按字符预估 + 功能点数双上限打包成多批，批间并发、失败隔离（部分批失败保留其余）。
    generated_test_points = await _generate_test_points_batched(feature_dim_inputs, shared_context)

    # 4. 转换为 TestPointSchema
    # 构建适用维度映射
    feature_applicable_dims: dict[str, list[str]] = {}
    for item in feature_dim_inputs:
        feature_applicable_dims[item["feature_id"]] = [d["name"] for d in item["applicable_dimensions"]]

    test_points: list[TestPointSchema] = []
    for idx, gtp in enumerate(generated_test_points, start=1):
        applicable = feature_applicable_dims.get(gtp.feature_id, [])
        # 如果适用维度为空（可能因 checkpoint 序列化丢失 feature_type），跳过裁剪检查
        if applicable and gtp.dimension not in applicable:
            logger.warning(
                "LLM generated test point for non-applicable dimension %s on feature %s, skipping",
                gtp.dimension,
                gtp.feature_id,
            )
            continue

        _PRIORITY_MAP: dict[str, Literal["P0", "P1", "P2", "P3"]] = {
            "P0": "P0",
            "P1": "P1",
            "P2": "P2",
            "P3": "P3",
        }
        priority = _PRIORITY_MAP.get(gtp.priority, "P2")

        tp = TestPointSchema(
            id=f"TP-{idx:03d}",
            feature_id=gtp.feature_id,
            dimension=gtp.dimension,
            description=gtp.description,
            priority=priority,
            derived_from=gtp.derived_from,
            applicable_dimensions=applicable,
        )
        test_points.append(tp)

    # 5. 重新编号（因可能有跳过的）
    for idx, tp in enumerate(test_points, start=1):
        tp.id = f"TP-{idx:03d}"

    # 6. 漏测 Bug 强制维度注入（硬约束#4）
    injector = MandatoryDimensionInjector()
    test_points = injector.inject_mandatory(test_points, parsed_context)

    return {
        "test_points": test_points,
        "current_stage": "test_points",
    }
