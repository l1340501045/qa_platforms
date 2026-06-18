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
from src.testcase_generator.stages.test_points.rule_anchor import (
    build_rule_anchored_test_points,
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


# ─── 质量属性维度信号门控（根因3：维度机械全展开）────────────────────────────────
#
# ApplicabilityFilter 仅按 feature_type 关键词放行维度，导致功能点描述里混入"列表/
# 搜索/接口"等词后，性能/安全/集成/分页等"质量属性维度"被机械放行；PRD 对它们只字
# 未提时，write_cases 只能产出 needs_spec 占位用例 → 用例虚胖。
# 门控：下表中的"质量属性/技术派生维度"必须在功能点上下文或全文档中命中触发信号才放行；
# 不在表中的维度（功能正确性、权限 access_control/permission_denied、基本输入校验/边界等
# 核心维度）恒放行，覆盖不受损。信号用具体词组，避免字段名（如"接口标识"）误命中。
_DIMENSION_GATE: dict[str, tuple[str, ...]] = {
    # 性能
    "response_time": ("性能", "响应时间", "响应速度", "加载时间", "耗时", "卡顿", "p95", "p99", "秒级", "毫秒", "ms内"),
    "throughput": ("吞吐", "并发量", "qps", "tps", "压测", "峰值流量", "高并发"),
    "resource_usage": ("内存占用", "cpu", "资源消耗", "内存泄漏", "电量", "磁盘io"),
    "large_data_volume": ("万级", "十万", "百万", "海量", "大数据量", "大批量", "数据量大", "数据量增长"),
    # 集成
    "api_contract": ("接口契约", "接口文档", "api接口", "调用接口", "接口返回", "接口参数", "openapi", "swagger", "状态码", "请求参数", "响应结构", "响应体"),
    "cross_system": ("第三方", "外部系统", "对接", "回调", "webhook", "熔断", "降级", "跨系统"),
    "data_sync": ("数据同步", "主从", "增量同步", "全量同步", "cdc", "数据一致性"),
    "event_driven": ("消息队列", "kafka", "rabbitmq", "事件驱动", "订阅", "发布消息", "死信", "消费消息"),
    # 安全（access_control / permission_denied 是权限核心，不门控）
    "input_injection": ("注入", "xss", "sql注入", "转义", "脚本攻击", "特殊字符过滤", "防注入"),
    "data_leakage": ("脱敏", "敏感信息", "敏感字段", "泄露", "隐私", "加密存储", "明文"),
    "authentication_security": ("密码强度", "暴力破解", "验证码", "csrf", "会话固定", "登录安全", "二次验证"),
    # 状态（技术性）
    "state_transition": ("状态机", "状态流转", "状态变更", "状态转换", "审核状态", "流转", "草稿", "驳回"),
    "concurrency_state": ("并发", "乐观锁", "悲观锁", "竞争条件", "原子性"),
    "recovery": ("断点续传", "断点", "崩溃恢复", "重连", "异常恢复", "事务回滚"),
    "cache_consistency": ("缓存", "击穿", "穿透", "雪崩"),
    "concurrent_conflict": ("并发", "冲突", "同时编辑", "超卖", "乐观锁", "悲观锁"),
    # 错误（网络/超时）
    "network_error": ("断网", "弱网", "网络异常", "网络错误", "重连", "请求超时", "网络超时", "网络中断"),
    "timeout": ("超时", "timeout", "长时间等待", "超时时间", "等待超时"),
    # 数据（技术性）
    "data_migration": ("数据迁移", "升级兼容", "历史数据", "schema变更", "存量数据"),
    "encoding_charset": ("编码", "字符集", "utf", "乱码", "emoji", "多字节", "特殊符号"),
    "data_calculation": ("计算", "统计", "公式", "汇总", "百分比", "金额计算", "精度", "四舍五入"),
    # 边界/可用性（分页/格式/无障碍/国际化）
    "pagination_boundary": ("分页", "翻页", "每页", "页码", "下一页", "首页", "末页", "上一页"),
    "format_validation": ("格式校验", "邮箱格式", "手机号", "日期格式", "正则", "金额格式", "url格式", "编号格式", "格式要求"),
    "accessibility": ("无障碍", "键盘导航", "屏幕阅读", "aria", "对比度", "可访问性"),
    "multi_language": ("多语言", "国际化", "i18n", "翻译", "rtl", "本地化", "语言切换"),
}


def _gate_quality_dimensions(
    dims: list[dict], feature_text: str, global_text: str
) -> list[dict]:
    """质量属性/技术派生维度的信号门控：上下文无相关信号则剔除该维度。

    功能点自身上下文或全文档任一处命中触发信号即放行（后者避免漏测技术方案文档定义
    的维度）；不在 _DIMENSION_GATE 中的核心维度恒放行。
    """
    ft = (feature_text or "").lower()
    gt = global_text or ""
    kept: list[dict] = []
    for dim in dims:
        signals = _DIMENSION_GATE.get(dim.get("name", ""))
        if signals is None:
            kept.append(dim)
            continue
        if any(sig in ft or sig in gt for sig in signals):
            kept.append(dim)
    return kept


# 内容规模分档（P1-1 修复）：按 feature.description 字数动态决定非核心维度上限 +
# **维度测试点数量上限**。审查发现：
#   - F-018 80 字 PRD → 84 case（tier 1 砍）
#   - 本 PRD §3 合并 2145 字（含 UI 原型表格）→ 78 测试点仍灌水（tier 3 砍）
#   - 大 PRD §5.x 模块 4000-7000 字（多子节）→ 进 tier 4 维持原门控
# 仅控制维度数量不够：LLM 在每个维度内还会展开 3-7 个测试点，故同时设"维度测试点上限"。
# 锚定测试点（带 rule_id）始终全部保留——它们是规则覆盖闸的依据，不受此截断影响。
#   tier 1 — feature ≤ 300 字 OR 非 spec 章节：仅核心维度，维度测试点 ≤ 0（仅锚定）
#   tier 2 — feature ≤ 1200 字（小型）：≤ 2 个非核心维度，维度测试点 ≤ 5
#   tier 3 — feature ≤ 3000 字（中型）：≤ 4 个非核心维度，维度测试点 ≤ 15
#   tier 4 — feature > 3000 字（大型）：维持 _gate_quality_dimensions 关键词门控，不截断
_TIER1_MAX_CHARS = 300
_TIER2_MAX_CHARS = 1200
_TIER3_MAX_CHARS = 3000
_TIER2_NON_CORE_LIMIT = 2
_TIER3_NON_CORE_LIMIT = 4
_TIER1_DIM_TP_CAP = 0
_TIER2_DIM_TP_CAP = 5
_TIER3_DIM_TP_CAP = 15


def _dim_tp_cap_for(section_kind: str, feature_desc_chars: int) -> int | None:
    """返回 feature 维度测试点上限；None 表示不截断（tier 4）。"""
    is_non_spec = section_kind in {"summary", "flow", "mock", "future", "tbd"}
    chars = feature_desc_chars or 0
    if is_non_spec or chars <= _TIER1_MAX_CHARS:
        return _TIER1_DIM_TP_CAP
    if chars <= _TIER2_MAX_CHARS:
        return _TIER2_DIM_TP_CAP
    if chars <= _TIER3_MAX_CHARS:
        return _TIER3_DIM_TP_CAP
    return None

# 稀薄/非 spec 章节仍允许保留的核心维度白名单（不被维度增强裁掉）。
# 选择标准：维度名以"功能正确性 / 输入校验 / 边界值 / 权限"为核心，覆盖 PRD 即便很短也
# 必然存在的基本可测点。其他维度（性能/集成/安全派生/网络/编码等）一律剔除。
_CORE_DIMENSIONS = frozenset({
    "functional_correctness", "happy_path", "negative_path",
    "invalid_input", "boundary_value", "format_validation",
    "access_control", "permission_denied",
    "state_transition",
})


def _gate_by_section_kind(
    dims: list[dict], section_kind: str, feature_desc_chars: int
) -> list[dict]:
    """章节性质 + 内容规模分档门控（P1-1 修复）：

    防止 LLM 对中小型 feature 机械展开 9 维度产生灌水（典例：F-018 80 字 → 84 case；
    本次 §3 合并 1500 字 → 78 测试点）。

    - section_kind in {summary, flow, mock, future, tbd}：整章不做维度增强（tier 1）
    - 否则按 feature.description 字数分档限制非核心维度数量
    - 不在 _DIMENSION_GATE 中的"质量属性维度"（已被 _gate_quality_dimensions 关键词门控
      过一道筛）按字数限额裁出最多 N 个；多出的按列表前后顺序保留前 N 个（稳定）。
    """
    is_non_spec = section_kind in {"summary", "flow", "mock", "future", "tbd"}
    chars = feature_desc_chars or 0

    # tier 1：仅核心维度
    if is_non_spec or chars <= _TIER1_MAX_CHARS:
        return [d for d in dims if d.get("name") in _CORE_DIMENSIONS]

    # tier 4：大型 feature 不再二次裁剪（保持原行为）
    if chars > _TIER3_MAX_CHARS:
        return dims

    # tier 2 / tier 3：核心全留 + 非核心按上限裁
    limit = _TIER2_NON_CORE_LIMIT if chars <= _TIER2_MAX_CHARS else _TIER3_NON_CORE_LIMIT
    kept: list[dict] = []
    non_core_count = 0
    for d in dims:
        if d.get("name") in _CORE_DIMENSIONS:
            kept.append(d)
            continue
        if non_core_count < limit:
            kept.append(d)
            non_core_count += 1
    return kept


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
    """分批并发调用 LLM 生成测试点。

    test_points_completeness_guard 开时：失败批整批重试 1 次（temperature 微调）→
    仍失败则拆单 feature 逐个调用（最大保全）。关时退回旧行为（失败批静默丢）。
    """
    if not feature_dim_inputs:
        return []

    batches = _pack_feature_batches(feature_dim_inputs)
    semaphore = asyncio.Semaphore(settings.llm_concurrency)

    async def _call_batch(
        batch_idx: int, feats: list[dict], *, temperature: float = 0.3
    ) -> list[GeneratedTestPoint] | None:
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
                    temperature=temperature,
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
    failed_batches: list[tuple[int, list[dict]]] = []
    for i, r in enumerate(results):
        if r is None:
            failed_batches.append((i, batches[i]))
        else:
            generated.extend(r)

    if not settings.test_points_completeness_guard:
        if len(failed_batches) == len(batches):
            raise RuntimeError(f"test-points 全部 {len(batches)} 批均失败，无法生成测试点")
        if failed_batches:
            logger.warning("test-points: %d/%d 批失败，已保留其余批结果", len(failed_batches), len(batches))
        return generated

    # ── guard 开：重试 + 单 feature 降级 ──────────────────────────────────────
    if failed_batches:
        logger.info("test-points completeness guard: %d 批失败，启动整批重试 (temperature=0.5)", len(failed_batches))
        retry_results = await asyncio.gather(
            *[_call_batch(idx, feats, temperature=0.5) for idx, feats in failed_batches]
        )

        still_failed: list[tuple[int, list[dict]]] = []
        for (idx, feats), r in zip(failed_batches, retry_results):
            if r is None:
                still_failed.append((idx, feats))
            else:
                generated.extend(r)

        if still_failed:
            logger.info(
                "test-points completeness guard: %d 批重试仍失败，拆单 feature 逐个调用",
                len(still_failed),
            )
            single_feats = [f for _, batch in still_failed for f in batch]
            single_results = await asyncio.gather(
                *[_call_batch(0, [f], temperature=0.5) for f in single_feats]
            )
            for r in single_results:
                if r is not None:
                    generated.extend(r)

    if not generated:
        raise RuntimeError(f"test-points 全部 {len(batches)} 批均失败（含重试+降级），无法生成测试点")

    all_fids = {f["feature_id"] for f in feature_dim_inputs}
    covered_fids = {tp.feature_id for tp in generated}
    missing = all_fids - covered_fids
    if missing:
        logger.warning("test-points completeness guard: %d feature 彻底失败无测试点: %s", len(missing), sorted(missing))

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

    # 全 PRD/技术文档文本：质量属性维度"信号门控"的依据（根因3）。仅当文档某处确有
    # 该维度信号（性能/安全注入/接口契约/状态机/缓存/分页等）才放行，避免对只字未提的
    # 维度机械全展开 → 灌水 needs_spec 占位用例。
    global_signal_text = "\n".join(
        f"{section.heading} {section.content}"
        for source in parsed_context.sources
        for section in source.sections
    ).lower()

    # 1. 为每个功能点进行适用性裁剪，构建 LLM 输入
    feature_dim_inputs = []
    for feature in parsed_context.features:
        feature_types = _infer_feature_types(feature)
        applicable_dims = applicability_filter.filter_dimensions(feature_types, all_dimensions)
        applicable_dims = _gate_quality_dimensions(
            applicable_dims, f"{feature.name}\n{feature.description}", global_signal_text
        )
        # P1-1 修复：章节性质门控 + 稀薄章节门控
        # summary/flow/mock/future/tbd 章节、或 description < 200 字的稀薄章节，
        # 不再机械全展 9 维度，仅保留核心维度（功能正确性/输入校验/边界/权限/状态）。
        section_kind = getattr(feature, "section_kind", "spec") or "spec"
        applicable_dims = _gate_by_section_kind(
            applicable_dims, section_kind, len(feature.description or "")
        )

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

    # 5a. 维度测试点数量分档截断（P1-1 强化）：按 feature 字数 tier 限制每 feature
    #     的维度测试点上限。锚定测试点（带 rule_id）始终全保留——它们是规则覆盖闸依据。
    #     这一步在重编号 + 漏测注入 + 锚点追加之前执行，仅作用在 LLM 生成的维度路径。
    feature_meta: dict[str, tuple[str, int]] = {}
    for feat in parsed_context.features:
        feature_meta[feat.id] = (
            getattr(feat, "section_kind", "spec") or "spec",
            len(feat.description or ""),
        )
    capped: list[TestPointSchema] = []
    capped_by_feat: dict[str, int] = {}
    dropped_by_feat: dict[str, int] = {}
    for tp in test_points:
        kind, chars = feature_meta.get(tp.feature_id, ("spec", 0))
        cap = _dim_tp_cap_for(kind, chars)
        if cap is None:
            capped.append(tp)
            continue
        if capped_by_feat.get(tp.feature_id, 0) < cap:
            capped.append(tp)
            capped_by_feat[tp.feature_id] = capped_by_feat.get(tp.feature_id, 0) + 1
        else:
            dropped_by_feat[tp.feature_id] = dropped_by_feat.get(tp.feature_id, 0) + 1
    if dropped_by_feat:
        logger.info(
            "test-points 分档截断: %s",
            ", ".join(f"{fid}↓{cnt}" for fid, cnt in dropped_by_feat.items()),
        )
    test_points = capped

    # 5b. 重新编号（因可能有跳过的 + tier 截断后空号）
    for idx, tp in enumerate(test_points, start=1):
        tp.id = f"TP-{idx:03d}"

    # 6. 漏测 Bug 强制维度注入（硬约束#4）
    injector = MandatoryDimensionInjector()
    test_points = injector.inject_mandatory(test_points, parsed_context)

    # 7. 规则驱动锚点：每条规则确定性产出 1 个携带 rule_id 的锚点测试点（覆盖闸的锚）。
    #    维度驱动路径（上面 1~6）保持不变，作为 breadth 增强（rule_id=None）。
    #    开关关或无规则台账时零影响，行为与历史一致。
    rules = state.get("rules") or []
    if settings.rule_driven_testpoints_enabled and rules:
        anchors = build_rule_anchored_test_points(
            rules, parsed_context.features, start_idx=len(test_points)
        )
        test_points.extend(anchors)
        # 统一重编号（保留 rule_id 等字段），避免与维度/强制注入测试点撞号
        for idx, tp in enumerate(test_points, start=1):
            tp.id = f"TP-{idx:03d}"
        logger.info(
            "test-points: 追加 %d 个规则锚点（规则台账 %d 条）", len(anchors), len(rules)
        )

    return {
        "test_points": test_points,
        "current_stage": "test_points",
    }
