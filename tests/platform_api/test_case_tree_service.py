"""用例树 Service 纯逻辑测试。"""

from uuid import uuid4

from src.platform_api.services.case_tree_service import CaseTreeService


def _case(
    title: str,
    source_section: str | None,
    derived_from: list[str] | None = None,
    *,
    bucket: str = "main",
    verdict: str = "grounded",
    review_issue_type: str | None = None,
    duplicate_of=None,
) -> dict:
    verification = {"bucket": bucket, "verdict": verdict}
    if review_issue_type:
        verification["review_issue_type"] = review_issue_type
    return {
        "id": uuid4(),
        "title": title,
        "priority": "P1",
        "trust_level": 1,
        "review_status": "pending",
        "iteration": 1,
        "bucket": bucket,
        "verdict": verdict,
        "verification": verification,
        "duplicate_of": duplicate_of,
        "provenance": {
            "derived_from": derived_from or ([source_section] if source_section else []),
            "source_section": source_section,
            "trust_level": 1,
        },
        "document_id": uuid4(),
        "document_title": "漫剧批创 PRD",
    }


def test_case_tree_uses_business_module_and_branch_path_for_new_batches():
    service = object.__new__(CaseTreeService)
    doc_id = uuid4()
    cases = [
        {
            **_case("标题包字数算法覆盖", "prd:漫剧批创初版功能PRD §5.6.1 字段与字数算法"),
            "document_id": doc_id,
        },
        {
            **_case("标题包自动拆包覆盖", "prd:漫剧批创初版功能PRD §5.6.2 自动拆包规则"),
            "document_id": doc_id,
        },
    ]

    tree = service._assemble_tree(cases)

    assert len(tree) == 1
    assert [module["module_name"] for module in tree[0]["modules"]] == ["标题包"]

    title_module = tree[0]["modules"][0]
    assert title_module["case_count"] == 2
    assert {tuple(branch["branch_path"]) for branch in title_module["branches"]} == {
        ("新建编辑", "字数算法"),
        ("自动拆包",),
    }
    assert len(title_module["cases"]) == 2


def test_case_tree_falls_back_to_source_section_for_legacy_batches():
    service = object.__new__(CaseTreeService)
    doc_id = uuid4()
    cases = [
        {
            **_case("推荐列表-正常加载", "推荐列表", ["t"]),
            "document_id": doc_id,
        },
        {
            **_case("推荐列表-空状态", "推荐列表", ["t"]),
            "document_id": doc_id,
        },
    ]

    tree = service._assemble_tree(cases)

    assert [module["module_name"] for module in tree[0]["modules"]] == ["推荐列表"]
    assert tree[0]["modules"][0]["case_count"] == 2


def test_case_tree_displays_review_required_as_human_readable_queue():
    service = object.__new__(CaseTreeService)
    doc_id = uuid4()
    cases = [
        {
            **_case("无法归类的新批次用例", "unresolved", []),
            "document_id": doc_id,
        }
    ]

    tree = service._assemble_tree(cases)

    assert [module["module_name"] for module in tree[0]["modules"]] == ["待分类"]
    module = tree[0]["modules"][0]
    assert module["branches"][0]["branch_name"] == "未匹配模块"
    assert module["branches"][0]["branch_path"] == ["未匹配模块"]


def test_case_tree_routes_unmatched_structured_prd_source_to_review_queue():
    service = object.__new__(CaseTreeService)
    doc_id = uuid4()
    cases = [
        {
            **_case(
                "bid_type 传入合法枚举 CUSTOM，接口正常",
                "prd:产品需求文档：小说批创系统 - 智擎版 v1.43 §7. 功能详细描述",
            ),
            "document_id": doc_id,
        }
    ]

    all_tree = service._assemble_tree(cases)
    stable_tree = service._assemble_tree(cases, exclude_review_required=True)

    assert [module["module_name"] for module in all_tree[0]["modules"]] == ["待分类"]
    assert all_tree[0]["modules"][0]["cases"][0]["classification_confidence"] == "unresolved"
    assert stable_tree == []


def test_case_tree_stable_view_excludes_review_required_queue():
    service = object.__new__(CaseTreeService)
    doc_id = uuid4()
    cases = [
        {
            **_case("标题包主集用例", "prd:漫剧批创初版功能PRD §5.6 标题包"),
            "document_id": doc_id,
        },
        {
            **_case("无法归类的主集用例", "unresolved", []),
            "document_id": doc_id,
        },
    ]

    tree = service._assemble_tree(cases, exclude_review_required=True)

    assert [module["module_name"] for module in tree[0]["modules"]] == ["标题包"]
    assert tree[0]["modules"][0]["case_count"] == 1


def test_case_tree_review_required_view_only_returns_review_queue():
    service = object.__new__(CaseTreeService)
    doc_id = uuid4()
    cases = [
        {
            **_case("标题包主集用例", "prd:漫剧批创初版功能PRD §5.6 标题包"),
            "document_id": doc_id,
        },
        {
            **_case("无法归类的主集用例", "unresolved", []),
            "document_id": doc_id,
        },
    ]

    tree = service._assemble_tree(cases, review_required_only=True)

    assert [module["module_name"] for module in tree[0]["modules"]] == ["待分类"]
    assert tree[0]["modules"][0]["case_count"] == 1


def test_case_tree_payload_exposes_duplicate_marker():
    service = object.__new__(CaseTreeService)
    doc_id = uuid4()
    duplicate_of = uuid4()
    cases = [
        {
            **_case(
                "标题包重复代表",
                "prd:漫剧批创初版功能PRD §5.6 标题包",
                duplicate_of=duplicate_of,
            ),
            "document_id": doc_id,
        }
    ]

    tree = service._assemble_tree(cases)

    case = tree[0]["modules"][0]["cases"][0]
    assert case["duplicate_of"] == duplicate_of
    assert case["is_duplicate"] is True


def test_case_tree_payload_exposes_review_issue_type_from_verification_json():
    service = object.__new__(CaseTreeService)
    doc_id = uuid4()
    cases = [
        {
            **_case(
                "PRD 自冲突样本",
                "prd:漫剧批创初版功能PRD §5.6 标题包",
                bucket="to_fix",
                verdict="conflict",
                review_issue_type="prd_conflict",
            ),
            "document_id": doc_id,
        }
    ]

    tree = service._assemble_tree(cases)

    case = tree[0]["modules"][0]["cases"][0]
    assert case["review_issue_type"] == "prd_conflict"


def test_case_tree_filters_by_review_issue_type():
    service = object.__new__(CaseTreeService)
    doc_id = uuid4()
    cases = [
        {
            **_case(
                "用例错误样本",
                "prd:漫剧批创初版功能PRD §5.6 标题包",
                bucket="to_fix",
                verdict="conflict",
                review_issue_type="case_wrong",
            ),
            "document_id": doc_id,
        },
        {
            **_case(
                "PRD 自冲突样本",
                "prd:漫剧批创初版功能PRD §5.6 标题包",
                bucket="to_fix",
                verdict="conflict",
                review_issue_type="prd_conflict",
            ),
            "document_id": doc_id,
        },
    ]

    tree = service._assemble_tree(cases, review_issue_type="case_wrong")

    assert tree[0]["modules"][0]["case_count"] == 1
    assert tree[0]["modules"][0]["cases"][0]["title"] == "用例错误样本"
