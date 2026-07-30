from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from src.testcase_generator.schemas.taxonomy import TaxonomyManifest, TaxonomySelectorFacts
from src.testcase_generator.services.taxonomy_manifest import manifest_hash

SYSTEM_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
DOCUMENT_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
CONTENT_HASH = "c" * 64
FEATURE_FINGERPRINT = "f" * 64


def _manifest_data() -> dict:
    return {
        "schema_version": 1,
        "system_id": str(SYSTEM_ID),
        "version": 1,
        "change_note": "首个业务分类版本",
        "created_by": "echo_lacey",
        "nodes": [
            {
                "stable_key": "asset-center",
                "node_type": "module",
                "display_name": "素材中心",
                "sort_order": 10,
            },
            {
                "stable_key": "asset-center.filter",
                "node_type": "capability",
                "display_name": "筛选与排序",
                "parent_stable_key": "asset-center",
                "sort_order": 10,
            },
        ],
        "mappings": [
            {
                "document_id": str(DOCUMENT_ID),
                "document_content_hash": CONTENT_HASH,
                "feature_fingerprint": FEATURE_FINGERPRINT,
                "scope": "test_point_selector",
                "selector": {"structural_key": "filter.sort"},
                "target_stable_key": "asset-center.filter",
                "related_stable_keys": [],
                "mapping_method": "manual",
                "confidence": 1.0,
                "reason": "PRD 明确描述筛选与排序能力",
                "review_status": "approved",
                "reviewed_by": "taxonomy_reviewer",
                "reviewed_at": datetime(2026, 7, 21, tzinfo=timezone.utc).isoformat(),
            }
        ],
    }


def _v2_manifest_data() -> dict:
    data = _manifest_data()
    data["schema_version"] = 2
    data["nodes"][0].update(
        {
            "definition": "管理投放过程中可复用的素材资产。",
            "scope_note": "包含素材查询与管理，不包含广告投放执行。",
        }
    )
    data["nodes"][1].update(
        {
            "definition": "按业务条件筛选素材，并按支持的字段调整结果顺序。",
            "scope_note": "包含筛选和排序，不包含素材上传与删除。",
            "in_scope_examples": [
                {
                    "text": "列表支持按创建时间排序。",
                    "document_content_hash": CONTENT_HASH,
                    "requirement_unit_id": f"ru_{'1' * 64}",
                }
            ],
            "out_of_scope_examples": [
                {
                    "text": "上传一个新素材。",
                    "document_content_hash": CONTENT_HASH,
                    "requirement_unit_id": f"ru_{'2' * 64}",
                }
            ],
        }
    )
    return data


def test_manifest_hash_is_independent_of_node_and_mapping_order() -> None:
    first = TaxonomyManifest.model_validate(_manifest_data())
    reordered_data = _manifest_data()
    reordered_data["nodes"].reverse()
    reordered_data["mappings"].reverse()
    second = TaxonomyManifest.model_validate(reordered_data)

    assert manifest_hash(first) == manifest_hash(second)


def test_v1_manifest_remains_v1_without_implicit_semantic_defaults() -> None:
    manifest = TaxonomyManifest.model_validate(_manifest_data())

    payload = manifest.model_dump(mode="json", exclude_none=True)

    assert payload["schema_version"] == 1
    assert "definition" not in payload["nodes"][0]
    assert "scope_note" not in payload["nodes"][0]
    assert "in_scope_examples" not in payload["nodes"][0]
    assert "out_of_scope_examples" not in payload["nodes"][0]


def test_v1_manifest_rejects_v2_semantics_without_explicit_version_upgrade() -> None:
    data = _manifest_data()
    data["nodes"][0]["definition"] = "不应静默升级"

    with pytest.raises(ValidationError, match="v1_semantics_forbidden"):
        TaxonomyManifest.model_validate(data)


@pytest.mark.parametrize("missing_field", ["definition", "scope_note"])
def test_v2_manifest_requires_node_definition_and_scope(missing_field: str) -> None:
    data = _v2_manifest_data()
    data["nodes"][0].pop(missing_field)

    with pytest.raises(ValidationError, match=f"v2_node_{missing_field}_required"):
        TaxonomyManifest.model_validate(data)


def test_v2_manifest_requires_grounded_evidence_for_active_capability() -> None:
    data = _v2_manifest_data()
    data["nodes"][1]["in_scope_examples"] = []

    with pytest.raises(ValidationError, match="v2_active_capability_in_scope_evidence_required"):
        TaxonomyManifest.model_validate(data)


def test_v2_manifest_rejects_same_evidence_as_in_and_out_of_scope() -> None:
    data = _v2_manifest_data()
    data["nodes"][1]["out_of_scope_examples"] = deepcopy(data["nodes"][1]["in_scope_examples"])

    with pytest.raises(ValidationError, match="scope_example_conflict"):
        TaxonomyManifest.model_validate(data)


def test_v2_manifest_hash_uses_set_semantics_for_scope_examples() -> None:
    first_data = _v2_manifest_data()
    first_data["nodes"][1]["in_scope_examples"].append(
        {
            "text": "筛选条件支持重置。",
            "document_content_hash": CONTENT_HASH,
            "requirement_unit_id": f"ru_{'3' * 64}",
        }
    )
    second_data = deepcopy(first_data)
    second_data["nodes"][1]["in_scope_examples"].reverse()

    assert manifest_hash(TaxonomyManifest.model_validate(first_data)) == manifest_hash(
        TaxonomyManifest.model_validate(second_data)
    )


def test_manifest_hash_uses_set_semantics_for_aliases_and_related_concepts() -> None:
    first_data = _manifest_data()
    first_data["nodes"].append(
        {
            "stable_key": "task-center",
            "node_type": "module",
            "display_name": "任务中心",
            "aliases": ["执行任务", "投放任务"],
        }
    )
    first_data["mappings"][0]["related_stable_keys"] = ["asset-center", "task-center"]
    second_data = deepcopy(first_data)
    second_data["nodes"][2]["aliases"].reverse()
    second_data["mappings"][0]["related_stable_keys"].reverse()

    assert manifest_hash(TaxonomyManifest.model_validate(first_data)) == manifest_hash(
        TaxonomyManifest.model_validate(second_data)
    )


def test_manifest_rejects_parent_cycle() -> None:
    data = _manifest_data()
    data["nodes"][0]["parent_stable_key"] = "asset-center.filter"

    with pytest.raises(ValidationError, match="parent_cycle"):
        TaxonomyManifest.model_validate(data)


def test_manifest_rejects_replacement_cycle() -> None:
    data = _manifest_data()
    data["nodes"][0].update({"node_status": "merged", "replacement_stable_key": "asset-center.filter"})
    data["nodes"][1].update({"node_status": "merged", "replacement_stable_key": "asset-center"})

    with pytest.raises(ValidationError, match="replacement_cycle"):
        TaxonomyManifest.model_validate(data)


def test_manifest_rejects_unknown_selector_field() -> None:
    data = _manifest_data()
    data["mappings"][0]["selector"] = {"title_regex": "筛选"}

    with pytest.raises(ValidationError, match="title_regex"):
        TaxonomyManifest.model_validate(data)


def test_manifest_rejects_selector_with_multiple_fact_types() -> None:
    data = _manifest_data()
    data["mappings"][0]["selector"] = {
        "structural_key": "filter.sort",
        "requirement_anchor": "REQ-001",
    }

    with pytest.raises(ValidationError, match="selector_requires_exactly_one_value"):
        TaxonomyManifest.model_validate(data)


def test_selector_facts_reject_duplicate_requirement_anchors() -> None:
    with pytest.raises(ValidationError, match="duplicate_requirement_anchor"):
        TaxonomySelectorFacts.model_validate(
            {
                "schema_version": 1,
                "feature_fingerprint": FEATURE_FINGERPRINT,
                "requirement_anchors": ["REQ-001", "REQ-001"],
            }
        )


def test_manifest_requires_review_metadata_for_approved_mapping() -> None:
    data = _manifest_data()
    data["mappings"][0]["reviewed_by"] = None
    data["mappings"][0]["reviewed_at"] = None

    with pytest.raises(ValidationError, match="reviewed_mapping_metadata_required"):
        TaxonomyManifest.model_validate(data)


def test_manifest_rejects_mapping_self_approval() -> None:
    data = _manifest_data()
    data["mappings"][0]["reviewed_by"] = data["created_by"]

    with pytest.raises(ValidationError, match="mapping_self_approval_forbidden"):
        TaxonomyManifest.model_validate(data)


def test_manifest_requires_timezone_aware_review_timestamp() -> None:
    data = _manifest_data()
    data["mappings"][0]["reviewed_at"] = "2026-07-21T10:00:00"

    with pytest.raises(ValidationError, match="reviewed_at_timezone_required"):
        TaxonomyManifest.model_validate(data)


@pytest.mark.parametrize(
    ("scope", "selector", "error_code"),
    [
        ("feature_default", {"rule_id": "R-001"}, "feature_default_selector_forbidden"),
        ("test_point_selector", None, "test_point_selector_required"),
    ],
)
def test_manifest_enforces_selector_scope(scope: str, selector: dict | None, error_code: str) -> None:
    data = _manifest_data()
    data["mappings"][0]["scope"] = scope
    data["mappings"][0]["selector"] = selector

    with pytest.raises(ValidationError, match=error_code):
        TaxonomyManifest.model_validate(data)


def test_manifest_rejects_mapping_to_inactive_node() -> None:
    data = _manifest_data()
    data["nodes"][1]["node_status"] = "deprecated"

    with pytest.raises(ValidationError, match="mapping_target_not_active"):
        TaxonomyManifest.model_validate(data)


def test_manifest_rejects_duplicate_mapping_identity() -> None:
    data = _manifest_data()
    data["mappings"].append(deepcopy(data["mappings"][0]))

    with pytest.raises(ValidationError, match="duplicate_mapping_identity"):
        TaxonomyManifest.model_validate(data)


def test_manifest_mapping_identity_is_scoped_by_document() -> None:
    data = _manifest_data()
    second_document_mapping = deepcopy(data["mappings"][0])
    second_document_mapping["document_id"] = "dddddddd-dddd-dddd-dddd-dddddddddddd"
    data["mappings"].append(second_document_mapping)

    manifest = TaxonomyManifest.model_validate(data)

    assert len(manifest.mappings) == 2
