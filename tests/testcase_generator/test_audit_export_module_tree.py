from __future__ import annotations

import json

from scripts.audit_case_reader import case_jsonl_files, feature_fallback_from_path, iter_case_records
from scripts.audit_export import (
    AUDIT_SCHEMA_VERSION,
    _branch_quality_flags,
    _dump_calibration_records,
    _dump_case_records,
    build_audit_tree,
    build_calibration_review,
    classify_case_for_audit,
)
from scripts.audit_global import _load_cases


def _record(
    case_id: str,
    *,
    title: str,
    source_section: str,
    derived_from: list[str] | None = None,
    verbatim_excerpt: str = "需求原文摘录",
    priority: str = "P1",
    verdict: str = "grounded",
    bucket: str = "main",
    duplicate_of: str | None = None,
    test_point_id: str = "TP-1",
    steps: list[dict] | None = None,
    expected_results: list[str] | None = None,
    dimensions: list[str] | None = None,
    review_issue_type: str | None = None,
) -> dict:
    verification = {"verdict": verdict, "bucket": bucket}
    if review_issue_type:
        verification["review_issue_type"] = review_issue_type
    return {
        "id": case_id,
        "title": title,
        "priority": priority,
        "trust_level": 1,
        "review_status": "pending",
        "verdict": verdict,
        "bucket": bucket,
        "preconditions": [],
        "steps": steps or [{"step_number": 1, "action": "执行", "input_data": "", "expected_result": "符合预期"}],
        "expected_results": expected_results or ["符合预期"],
        "dimensions": dimensions or ["functional_correctness"],
        "provenance": {
            "derived_from": derived_from or [source_section],
            "source_section": source_section,
            "verbatim_excerpt": verbatim_excerpt,
            "trust_level": 1,
        },
        "verification": verification,
        "confidence_note": None,
        "test_point_id": test_point_id,
        "duplicate_of": duplicate_of,
        "is_duplicate": duplicate_of is not None,
    }


def test_classify_title_package_keyword_wins_over_batch_create_section_prefix():
    record = _record(
        "TC-1",
        title="标题包槽位按候选池循环分配",
        source_section="prd:漫剧批创初版功能PRD §5.8.6 标题包选择",
    )

    cls = classify_case_for_audit(record)

    assert cls["business_module"] == "标题包"
    assert cls["branch_path"] == ["批创联动", "标题分配"]
    assert "§5.8.6 标题包选择" in cls["source_refs"][0]


def test_title_package_batch_create_section_uses_source_branch_when_title_has_no_branch_keyword():
    record = _record(
        "TC-title-assign",
        title="总广告数超过总标题数时按槽顺序回到第一个槽继续复用",
        source_section="prd:漫剧批创初版功能PRD §5.8.6 标题包",
    )

    cls = classify_case_for_audit(record)

    assert cls["business_module"] == "标题包"
    assert cls["branch_path"] == ["批创联动", "标题分配"]


def test_classify_source_section_wins_over_alias_noise():
    record = _record(
        "TC-asset-noise",
        title="切换漫剧后各创意组已选素材被清空",
        source_section="prd:漫剧批创初版功能PRD §5.8.5 创意素材",
        verbatim_excerpt=(
            "切换漫剧：清空已选投放链接与各创意组已选素材；其余配置（商品 / 标题包 / 定向包 / 预算等）保持不变"
        ),
    )

    cls = classify_case_for_audit(record)

    assert cls["business_module"] == "素材中心"
    assert cls["branch_path"] == ["创意素材"]
    assert cls["classification_reason"].startswith("source:")


def test_classify_named_and_monitoring_sections_before_alias_fallback():
    field_linkage = _record(
        "TC-field-linkage",
        title="CBO付费ROI-内部枚举复用历史CBO系数字段位，底层参数口径不变",
        source_section="prd:漫剧批创初版功能PRD §六类投放方式字段对照",
    )
    monitoring = _record(
        "TC-monitoring",
        title="验证IAP链接包含全部35个query参数",
        source_section="prd:漫剧批创初版功能PRD §7.1.1 本期预置监测链接（全文）",
        verbatim_excerpt="链接来源包含预置监测链接全文",
    )

    assert classify_case_for_audit(field_linkage)["business_module"] == "批量创建广告"
    monitoring_cls = classify_case_for_audit(monitoring)
    assert monitoring_cls["business_module"] == "监测链接"
    assert monitoring_cls["branch_path"] == ["本期预置监测链接"]


def test_cross_cutting_sections_keep_business_module_with_tag():
    field_constraint = _record(
        "TC-field",
        title="快搜功能-输入1001个账户ID时被拒绝并提示",
        source_section="prd:漫剧批创初版功能PRD §9.2 各模块字段约束（续表 2）",
        verbatim_excerpt="账户选择-快搜 | 单次快搜 ID 上限 | ≤ 1000 个。",
    )
    permission = _record(
        "TC-permission",
        title="任务数据权限——投手仅可见本人创建的任务",
        source_section="prd:漫剧批创初版功能PRD §10.1 角色分类",
        verbatim_excerpt="投手默认只读 / 写本人创建的漫剧 / 标题包 / 定向包 / 账户授权 / 任务等。",
    )

    field_cls = classify_case_for_audit(field_constraint)
    assert field_cls["business_module"] == "账户授权"
    assert field_cls["branch_path"] == ["字段约束"]
    assert field_cls["cross_cutting_tags"] == ["field_constraint"]

    permission_cls = classify_case_for_audit(permission)
    assert permission_cls["business_module"] == "任务中心"
    assert permission_cls["branch_path"] == ["权限"]
    assert permission_cls["cross_cutting_tags"] == ["permission"]


def test_branch_path_canonicalizes_source_heading_artifacts():
    naming = _record(
        "TC-naming",
        title="<漫剧名>通配符替换为[BF_<漫剧简称>]格式",
        source_section="prd:漫剧批创初版功能PRD §5.8.11 命名通配符（项目名称 / 广告名称 / 任务名称）",
    )
    filtering = _record(
        "TC-filter",
        title="过滤低效/拒审不依赖媒体评估接口",
        source_section="prd:漫剧批创初版功能PRD §5.5.3.4 低效 / 拒审过滤",
    )
    event_asset = _record(
        "TC-event",
        title="CBO激活投放方式下优化目标为「激活」时参数对照表一致性验证",
        source_section="prd:漫剧批创初版功能PRD §8.3 优化目标 → 事件资产映射表",
    )

    naming_cls = classify_case_for_audit(naming)
    filtering_cls = classify_case_for_audit(filtering)
    event_cls = classify_case_for_audit(event_asset)

    assert naming_cls["branch_path"] == ["命名通配符"]
    assert filtering_cls["branch_path"] == ["媒体评估与过滤", "低效拒审过滤"]
    assert event_cls["branch_path"] == ["事件资产映射"]
    assert _branch_quality_flags(naming_cls["branch_path"]) == []
    assert _branch_quality_flags(filtering_cls["branch_path"]) == []
    assert _branch_quality_flags(event_cls["branch_path"]) == []


def test_classify_module_ignores_document_title_noise_before_section_prefix():
    record = _record(
        "TC-2",
        title="任务状态机执行中到成功流转",
        source_section="prd:漫剧批创初版功能PRD §5.9.3 任务状态机",
    )

    cls = classify_case_for_audit(record)

    assert cls["business_module"] == "任务中心"


def test_unresolved_source_uses_narrow_business_title_fallbacks():
    cases = [
        (
            _record(
                "TC-owner",
                title="批量修改投放人按钮文案显示已选数量N",
                source_section="unresolved",
                derived_from=[],
            ),
            "账户授权",
        ),
        (
            _record(
                "TC-media-eval",
                title="媒体评估接口失败时素材的 media_evaluation_tags 保留上一次成功值",
                source_section="unresolved",
                derived_from=[],
            ),
            "素材中心",
        ),
        (
            _record(
                "TC-task-state",
                title="不同任务状态下「复用」操作均常显可用",
                source_section="unresolved",
                derived_from=[],
            ),
            "任务中心",
        ),
        (
            _record(
                "TC-cancelled-task",
                title="「已取消」状态任务-操作列仅展示复用按钮",
                source_section="unresolved",
                derived_from=[],
            ),
            "任务中心",
        ),
    ]

    for record, expected_module in cases:
        cls = classify_case_for_audit(record)
        assert cls["business_module"] == expected_module
        assert cls["classification_reason"].startswith("alias:")

    branch_expectations = {
        "TC-owner": ["投放人管理"],
        "TC-media-eval": ["媒体评估与过滤"],
        "TC-task-state": ["任务状态与操作"],
        "TC-cancelled-task": ["任务状态与操作"],
    }
    for record, _ in cases:
        cls = classify_case_for_audit(record)
        assert cls["branch_path"] == branch_expectations[record["id"]]


def test_build_audit_tree_groups_title_package_subsections_under_one_module():
    records = [
        _record(
            "TC-1",
            title="标题包名称字数算法校验",
            source_section="prd:漫剧批创初版功能PRD §5.6.1 字段与字数算法",
        ),
        _record(
            "TC-2",
            title="标题包自动拆包规则校验",
            source_section="prd:漫剧批创初版功能PRD §5.6.2 自动拆包规则",
        ),
        _record(
            "TC-3",
            title="标题包槽位按候选池循环分配",
            source_section="prd:漫剧批创初版功能PRD §5.8.6 标题包选择",
        ),
    ]

    tree = build_audit_tree(records)

    assert set(tree["modules"]) == {"标题包"}
    title_module = tree["modules"]["标题包"]
    assert len(title_module["case_records"]) == 3
    assert set(title_module["branches"]) == {
        ("新建编辑", "字数算法"),
        ("自动拆包",),
        ("批创联动", "标题分配"),
    }


def test_build_audit_tree_indexes_all_source_refs_for_reverse_lookup():
    records = [
        _record(
            "TC-1",
            title="标题包联动批创标题区",
            source_section="prd:漫剧批创初版功能PRD §5.8.6 标题包选择",
            derived_from=[
                "prd:漫剧批创初版功能PRD §5.6 标题包",
                "prd:漫剧批创初版功能PRD §5.8.6 标题包选择",
            ],
        )
    ]

    tree = build_audit_tree(records)

    assert set(tree["source_sections"]) == {
        "prd:漫剧批创初版功能PRD §5.6 标题包",
        "prd:漫剧批创初版功能PRD §5.8.6 标题包选择",
    }
    assert tree["source_sections"]["prd:漫剧批创初版功能PRD §5.6 标题包"][0]["id"] == "TC-1"
    assert tree["source_sections"]["prd:漫剧批创初版功能PRD §5.8.6 标题包选择"][0]["id"] == "TC-1"


def test_dump_writes_business_module_tree_and_source_section_lookup(tmp_path):
    doc_content = """# 5.6 标题包

## 5.6.1 字段与字数算法
标题包名称需要校验字数算法。

## 5.6.2 自动拆包规则
标题包支持自动拆包。

# 5.8 批量创建广告

## 5.8.6 标题包选择
批创标题区按标题包候选池分配。
"""
    records = [
        _record(
            "TC-1",
            title="标题包名称字数算法校验",
            source_section="prd:漫剧批创初版功能PRD §5.6.1 字段与字数算法",
        ),
        _record(
            "TC-2",
            title="标题包自动拆包规则校验",
            source_section="prd:漫剧批创初版功能PRD §5.6.2 自动拆包规则",
        ),
        _record(
            "TC-3",
            title="完全未知行为",
            source_section="unresolved",
            derived_from=[],
        ),
    ]

    index = _dump_case_records(
        batch_id="batch-1",
        document_id="doc-1",
        document_title="测试 PRD",
        generation_config={"quality_profile": "best_practice_default_2026_07"},
        doc_content=doc_content,
        image_captions={},
        case_records=records,
        point_records=[],
        out_dir=tmp_path,
    )

    assert index["audit_schema_version"] == AUDIT_SCHEMA_VERSION
    assert index["generation_config"] == {"quality_profile": "best_practice_default_2026_07"}
    assert index["module_count"] == 1
    assert index["modules"][0]["module_name"] == "标题包"
    assert sorted(branch["branch_path"] for branch in index["modules"][0]["branches"]) == [
        ["新建编辑", "字数算法"],
        ["自动拆包"],
    ]
    assert index["source_section_count"] == 3
    assert index["source_ref_count"] == 3
    assert index["review_required"]["unresolved_module"]["case_count"] == 1

    # modules/ 是业务模块树，不再生成旧式 modules/*.cases.jsonl 平铺文件。
    assert not list((tmp_path / "modules").glob("*.cases.jsonl"))
    assert list((tmp_path / "modules").glob("*/branches/**/cases.jsonl"))
    assert list((tmp_path / "by_source_section").glob("*.cases.jsonl"))
    assert (tmp_path / "_review_required" / "unresolved_module" / "cases.jsonl").exists()

    index_on_disk = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert index_on_disk["audit_schema_version"] == AUDIT_SCHEMA_VERSION
    assert index_on_disk["modules"][0]["source_sections"]


def test_dump_index_exposes_non_duplicate_quality_metrics(tmp_path):
    records = [
        _record(
            "TC-1",
            title="标题包名称必填",
            source_section="prd:漫剧批创初版功能PRD §5.6 标题包",
            priority="P0",
            bucket="main",
            verdict="grounded",
            test_point_id="TP-A",
        ),
        _record(
            "TC-2",
            title="标题包名称待澄清",
            source_section="prd:漫剧批创初版功能PRD §5.6 标题包",
            priority="P1",
            bucket="needs_spec",
            verdict="undefined",
            test_point_id="TP-A",
            steps=[
                {"step_number": 1, "action": "输入", "input_data": "", "expected_result": "显示"},
                {"step_number": 2, "action": "保存", "input_data": "", "expected_result": "待澄清"},
            ],
        ),
        _record(
            "TC-3",
            title="标题包名称必填重复",
            source_section="prd:漫剧批创初版功能PRD §5.6 标题包",
            priority="P0",
            bucket="main",
            verdict="grounded",
            duplicate_of="TC-1",
            test_point_id="TP-A",
        ),
        _record(
            "TC-4",
            title="完全未知行为",
            source_section="unresolved",
            derived_from=[],
            priority="P2",
            bucket="to_fix",
            verdict="conflict",
            test_point_id="TP-B",
        ),
    ]

    index = _dump_case_records(
        batch_id="batch-1",
        document_id="doc-1",
        document_title="测试 PRD",
        generation_config={},
        doc_content="# 5.6 标题包\n正文",
        image_captions={},
        case_records=records,
        point_records=[],
        out_dir=tmp_path,
    )

    assert index["active_case_count"] == 4
    assert index["duplicate_count"] == 1
    assert index["non_duplicate_case_count"] == 3
    assert index["stable_execution_case_count"] == 1
    assert index["bucket_dist"] == {"main": 2, "needs_spec": 1, "to_fix": 1}
    assert index["non_duplicate_bucket_dist"] == {"main": 1, "needs_spec": 1, "to_fix": 1}
    assert index["priority_dist"] == {"P0": 2, "P1": 1, "P2": 1}
    assert index["non_duplicate_priority_dist"] == {"P0": 1, "P1": 1, "P2": 1}
    assert index["verdict_dist"] == {"grounded": 2, "undefined": 1, "conflict": 1}
    assert index["non_duplicate_verdict_dist"] == {"grounded": 1, "undefined": 1, "conflict": 1}
    assert index["one_step_case_count"] == 3
    assert index["non_duplicate_one_step_case_count"] == 2
    assert index["stable_execution_one_step_case_count"] == 1
    assert index["max_cases_per_test_point"] == 3
    assert index["non_duplicate_max_cases_per_test_point"] == 2
    assert index["unresolved_module_count"] == 1
    assert index["non_duplicate_unresolved_module_count"] == 1
    assert index["review_required"]["unresolved_module"]["non_duplicate_bucket_dist"] == {"to_fix": 1}


def test_dump_index_exposes_machine_recomputable_quality_diagnostics(tmp_path):
    records = [
        _record(
            "TC-submit",
            title="批创页提交后写入batch_tasks并进入待提交状态",
            source_section="prd:漫剧批创初版功能PRD §5.8.13 提交逻辑",
            priority="P0",
            bucket="main",
            verdict="grounded",
            expected_results=["任务写入batch_tasks，状态为待提交"],
            dimensions=["state_transition"],
            steps=[
                {
                    "step_number": 1,
                    "action": "点击提交",
                    "input_data": "",
                    "expected_result": "任务写入batch_tasks，状态为待提交",
                }
            ],
        ),
        _record(
            "TC-display",
            title="入口页Tab按钮文案展示",
            source_section="prd:漫剧批创初版功能PRD §5.6.0 入口与页面预览",
            priority="P0",
            bucket="needs_spec",
            verdict="undefined",
            expected_results=["页面正常显示"],
            review_issue_type="case_wrong",
        ),
        _record(
            "TC-unresolved",
            title="完全未知P0行为",
            source_section="unresolved",
            derived_from=[],
            priority="P0",
            bucket="main",
            verdict="grounded",
            expected_results=["符合预期"],
            duplicate_of="TC-display",
            review_issue_type="verify_uncertain",
        ),
        _record(
            "TC-vague",
            title="标题包保存后展示正确",
            source_section="prd:漫剧批创初版功能PRD §5.6 标题包",
            priority="P1",
            bucket="main",
            verdict="grounded",
            expected_results=["保存后信息正确"],
        ),
    ]

    index = _dump_case_records(
        batch_id="batch-1",
        document_id="doc-1",
        document_title="测试 PRD",
        generation_config={},
        doc_content="# 5.6 标题包\n正文\n# 5.8 批量创建广告\n## 5.8.13 提交逻辑\n正文",
        image_captions={},
        case_records=records,
        point_records=[],
        out_dir=tmp_path,
    )

    diagnostics = index["quality_diagnostics"]
    all_diag = diagnostics["all"]
    nondup_diag = diagnostics["non_duplicate"]
    stable_diag = diagnostics["stable"]

    assert index["review_issue_type_dist"] == {"case_wrong": 1, "verify_uncertain": 1}
    assert index["non_duplicate_review_issue_type_dist"] == {"case_wrong": 1}

    assert all_diag["p0_count"] == 3
    assert all_diag["by_review_issue_type"] == {"case_wrong": 1, "verify_uncertain": 1}
    assert all_diag["p0_needs_spec_count"] == 1
    assert all_diag["p0_review_required_count"] == 1
    assert all_diag["p0_structural_signal_count"] == 1
    assert all_diag["p0_business_risk_signal_count"] == 1
    assert all_diag["p0_low_value_display_like_count"] == 1
    assert all_diag["vague_expected_count"] == 3
    assert all_diag["pure_vague_expected_count"] == 3
    assert all_diag["critical_flow_coverage"]["batch_submit"]["case_count"] == 1
    assert all_diag["critical_flow_coverage"]["batch_submit"]["p0_count"] == 1

    assert nondup_diag["case_count"] == 3
    assert nondup_diag["by_review_issue_type"] == {"case_wrong": 1}
    assert nondup_diag["p0_count"] == 2
    assert nondup_diag["p0_review_required_count"] == 0
    assert nondup_diag["p0_low_value_display_like_count"] == 1
    assert nondup_diag["pure_vague_expected_count"] == 2
    assert nondup_diag["samples"]["p0_low_value_display_like"][0]["id"] == "TC-display"

    assert stable_diag["case_count"] == 2
    assert stable_diag["by_review_issue_type"] == {}
    assert stable_diag["p0_count"] == 1
    assert stable_diag["p0_ratio"] == 0.5
    assert stable_diag["p0_by_bucket"] == {"main": 1}
    assert stable_diag["p0_by_verdict"] == {"grounded": 1}
    assert stable_diag["p0_needs_spec_count"] == 0
    assert stable_diag["p0_review_required_count"] == 0
    assert stable_diag["p0_low_value_display_like_count"] == 0
    assert stable_diag["vague_expected_count"] == 1
    assert stable_diag["pure_vague_expected_count"] == 1


def test_calibration_review_samples_across_branches_and_flags_dirty_branch():
    records = [
        _record(
            "TC-1",
            title="标题包名称字数算法校验",
            source_section="prd:漫剧批创初版功能PRD §5.6.1 字段与字数算法",
        ),
        _record(
            "TC-2",
            title="标题包自动拆包规则校验",
            source_section="prd:漫剧批创初版功能PRD §5.6.2 自动拆包规则",
        ),
        _record(
            "TC-3",
            title="全局字段边界校验",
            source_section="prd:漫剧批创初版功能PRD §9.2 1）",
        ),
    ]

    calibration = build_calibration_review(build_audit_tree(records))

    title_samples = [sample for sample in calibration["samples"] if sample["business_module"] == "标题包"]
    assert {tuple(sample["branch_path"]) for sample in title_samples} == {
        ("新建编辑", "字数算法"),
        ("自动拆包",),
    }
    dirty_sample = next(sample for sample in calibration["samples"] if sample["case_id"] == "TC-3")
    assert dirty_sample["business_module"] == "全局规则与字段约束"
    assert dirty_sample["branch_path"] == ["字段约束"]
    assert dirty_sample["cross_cutting_tags"] == ["field_constraint"]
    assert dirty_sample["quality_flags"] == []
    assert calibration["dirty_branch_name_count"] == 0
    assert calibration["gate_targets"]["module_accuracy"] == 0.95


def test_branch_quality_flags_heading_artifact_from_leaked_heading_text():
    assert "heading_artifact" in _branch_quality_flags(("/ 广告名称 / 任务名称）",))


def test_calibration_dump_writes_independent_review_package(tmp_path):
    records = [
        _record(
            "TC-1",
            title="标题包名称字数算法校验",
            source_section="prd:漫剧批创初版功能PRD §5.6.1 字段与字数算法",
        ),
        _record(
            "TC-2",
            title="标题包自动拆包规则校验",
            source_section="prd:漫剧批创初版功能PRD §5.6.2 自动拆包规则",
        ),
        _record(
            "TC-3",
            title="完全未知行为",
            source_section="unresolved",
            derived_from=[],
        ),
    ]

    index = _dump_calibration_records(
        doc_content="# 5.6 标题包\n\n## 5.6.1 字段与字数算法\n正文",
        image_captions={"img": "caption"},
        case_records=records,
        out_dir=tmp_path,
    )

    assert index["calibration_schema_version"] == 1
    assert index["sample_count"] == 3
    assert index["unresolved_count"] == 1
    assert (tmp_path / "README.md").exists()
    assert (tmp_path / "taxonomy_candidate.json").exists()
    assert (tmp_path / "calibration_samples.jsonl").exists()
    assert list((tmp_path / "samples").glob("*.md"))
    assert not (tmp_path / "modules").exists()

    sample = json.loads((tmp_path / "calibration_samples.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert sample["review"] == {
        "module_correct": None,
        "corrected_module": "",
        "branch_correct": None,
        "corrected_branch_path": [],
        "should_be_review_required": None,
        "review_notes": "",
    }
    taxonomy = json.loads((tmp_path / "taxonomy_candidate.json").read_text(encoding="utf-8"))
    assert taxonomy["review_status"] == "candidate_needs_calibration"


def test_audit_global_loads_nested_module_tree_cases_and_deduplicates(tmp_path):
    """全局横切分析必须读取新版 modules/<模块>/branches/**/cases.jsonl。"""
    case_a = {"id": "TC-A", "title": "标题包用例"}
    case_b = {"id": "TC-B", "title": "账户授权用例"}
    first = tmp_path / "modules" / "标题包" / "branches" / "自动拆包" / "cases.jsonl"
    second = tmp_path / "modules" / "账户授权" / "branches" / "权限" / "cases.jsonl"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text(
        "\n".join(json.dumps(case, ensure_ascii=False) for case in [case_a, case_b]) + "\n",
        encoding="utf-8",
    )
    second.write_text(json.dumps(case_a, ensure_ascii=False) + "\n", encoding="utf-8")

    cases = _load_cases(tmp_path)

    assert {case["id"] for case in cases} == {"TC-A", "TC-B"}
    assert len(cases) == 2


def test_audit_case_reader_prefers_nested_module_tree_and_deduplicates(tmp_path):
    """离线审查脚本应统一读取新版模块树，重复出现在多个分支的 case 只算一次。"""
    nested = tmp_path / "modules" / "标题包" / "branches" / "自动拆包" / "cases.jsonl"
    legacy = tmp_path / "modules" / "legacy.cases.jsonl"
    nested.parent.mkdir(parents=True)
    legacy.parent.mkdir(parents=True, exist_ok=True)

    nested.write_text(
        "\n".join(
            json.dumps(case, ensure_ascii=False)
            for case in [
                {"id": "TC-A", "title": "标题包 A"},
                {"id": "TC-B", "title": "标题包 B"},
                {"id": "TC-A", "title": "重复 A"},
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    legacy.write_text(json.dumps({"id": "TC-OLD", "title": "旧平铺"}, ensure_ascii=False), encoding="utf-8")

    records = [record for _, _, record in iter_case_records(tmp_path)]

    assert case_jsonl_files(tmp_path) == [nested]
    assert [record["id"] for record in records] == ["TC-A", "TC-B"]


def test_audit_case_reader_legacy_fallback_and_nested_feature_group(tmp_path):
    """旧审查包仍可读；新版嵌套路径的 feature fallback 不能退化成 cases。"""
    legacy = tmp_path / "modules" / "99__prd_任务中心.cases.jsonl"
    nested = tmp_path / "modules" / "账户授权" / "branches" / "权限" / "字段约束" / "cases.jsonl"
    legacy.parent.mkdir(parents=True)
    nested.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"id": "TC-OLD", "title": "旧平铺"}, ensure_ascii=False) + "\n", encoding="utf-8")

    assert case_jsonl_files(tmp_path) == [legacy]
    assert feature_fallback_from_path(legacy) == "99__prd_任务中心"
    assert feature_fallback_from_path(nested) == "账户授权/权限/字段约束"
