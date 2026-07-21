"""阶段命名统一 — 内部 key → 对外 canonical 名"""

# 对外 canonical 阶段名（连字符版，与契约一致）
STAGE_CANONICAL: dict[str, str] = {
    "parse": "parse",
    "comprehend": "comprehend",
    "gate": "gate",  # Gate 不是独立节点但在进度展示里显示
    "test_points": "test-points",
    "write_cases": "write-cases",
    "review": "review-cases",
    "export": "export",
}

# 反向映射
STAGE_INTERNAL: dict[str, str] = {v: k for k, v in STAGE_CANONICAL.items()}

# LangGraph 内部节点比平台展示阶段更细。平台进度只展示 7 个稳定阶段，
# 因此内部观测节点必须归并后再写入 test_batches.current_stage。
NODE_PROGRESS_STAGE: dict[str, str] = {
    "parse": "parse",
    "comprehend": "comprehend",
    "interrupt": "comprehend",
    "apply_clarification": "comprehend",
    "gate": "gate",
    "rule_extract": "gate",
    "test_points": "test_points",
    "write_cases": "write_cases",
    "review": "review",
    "backfill": "review",
    "verify": "review",
    "dedup": "review",
    "export": "export",
}

NEXT_PROGRESS_STAGE_AFTER_NODE: dict[str, str] = {
    "parse": "comprehend",
    "comprehend": "gate",
    "interrupt": "comprehend",
    "apply_clarification": "gate",
    "rule_extract": "test_points",
    "test_points": "write_cases",
    "write_cases": "review",
    "review": "review",
    "backfill": "review",
    "verify": "review",
    "dedup": "export",
    "export": "export",
}


def to_canonical(internal_name: str) -> str:
    """内部名 → 对外名"""
    return STAGE_CANONICAL.get(internal_name, internal_name)


def to_internal(canonical_name: str) -> str:
    """对外名 → 内部名"""
    return STAGE_INTERNAL.get(canonical_name, canonical_name)


def to_progress_internal(stage_name: str) -> str:
    """任意内部/对外阶段名 → 可写入 current_stage 的内部进度阶段名。"""
    internal_name = to_internal(stage_name)
    return NODE_PROGRESS_STAGE.get(internal_name, internal_name)


def to_progress_canonical(stage_name: str) -> str:
    """任意内部/对外阶段名 → 前端可展示的 canonical 进度阶段名。"""
    return to_canonical(to_progress_internal(stage_name))


def next_progress_stage_after_node(node_name: str) -> str:
    """LangGraph 节点完成后，平台应显示的下一段运行中阶段。"""
    internal_name = to_internal(node_name)
    next_stage = NEXT_PROGRESS_STAGE_AFTER_NODE.get(internal_name, internal_name)
    return to_progress_internal(next_stage)


# 完整阶段列表（按执行顺序）
PIPELINE_STAGES = ["parse", "comprehend", "gate", "test-points", "write-cases", "review-cases", "export"]
