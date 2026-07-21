from __future__ import annotations

import hashlib
from collections.abc import Sequence
from uuid import UUID

import pytest
from pydantic import ValidationError

from src.testcase_generator.schemas.requirement_unit import (
    RequirementUnit,
    build_requirement_unit_id,
    build_source_quote_hash,
)
from src.testcase_generator.schemas.taxonomy_resolution import TaxonomyResolutionPolicy
from src.testcase_generator.services.taxonomy_candidate_retriever import (
    TaxonomyCandidateRetriever,
    TaxonomyRetrievalError,
    TaxonomySearchConcept,
)

SYSTEM_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
DOCUMENT_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
TAXONOMY_VERSION_ID = UUID("11111111-1111-1111-1111-111111111111")
SYNC_CONCEPT_ID = UUID("22222222-2222-2222-2222-222222222222")
FILTER_CONCEPT_ID = UUID("33333333-3333-3333-3333-333333333333")
INACTIVE_CONCEPT_ID = UUID("44444444-4444-4444-4444-444444444444")
CONTENT_HASH = "c" * 64
MANIFEST_HASH = "d" * 64


def _policy(**overrides) -> TaxonomyResolutionPolicy:
    payload = {
        "schema_version": 1,
        "top_k": 3,
        "minimum_score": 0.8,
        "minimum_margin": 0.1,
        "out_of_scope_conflict_score": 0.9,
        "decision_context_max_chars": 24_000,
        "require_grounding": True,
        "allowed_node_types": ["module", "capability"],
        "allowed_node_statuses": ["active"],
        "model_role": "taxonomy_resolver",
        "model_revision": "resolver@1",
        "fail_behavior": "abstain",
        "auto_accept_signal": "retrieval_score_margin",
    }
    payload.update(overrides)
    return TaxonomyResolutionPolicy.model_validate(payload)


def _concepts() -> list[TaxonomySearchConcept]:
    return [
        TaxonomySearchConcept.model_validate(
            {
                "taxonomy_version_id": str(TAXONOMY_VERSION_ID),
                "concept_id": str(SYNC_CONCEPT_ID),
                "stable_key": "product.sync",
                "node_type": "capability",
                "node_status": "active",
                "display_name": "5.4 商品同步",
                "aliases": ["巨量商品同步"],
                "definition": "从巨量平台拉取商品数据并更新本地商品库。",
                "scope_note": "只负责同步与状态更新，不负责人工创建商品。",
                "in_scope_examples": [
                    {
                        "text": "商品库每天从巨量平台同步。",
                        "document_content_hash": CONTENT_HASH,
                        "requirement_unit_id": f"ru_{'1' * 64}",
                    }
                ],
                "out_of_scope_examples": [
                    {
                        "text": "点击按钮单个新建商品。",
                        "document_content_hash": CONTENT_HASH,
                        "requirement_unit_id": f"ru_{'2' * 64}",
                    }
                ],
            }
        ),
        TaxonomySearchConcept.model_validate(
            {
                "taxonomy_version_id": str(TAXONOMY_VERSION_ID),
                "concept_id": str(FILTER_CONCEPT_ID),
                "stable_key": "asset.filter",
                "node_type": "capability",
                "node_status": "active",
                "display_name": "筛选与排序",
                "aliases": ["条件过滤"],
                "definition": "按条件过滤列表并调整结果顺序。",
                "scope_note": "包含筛选、重置和排序。",
                "in_scope_examples": [
                    {
                        "text": "素材列表支持按条件筛选并重置。",
                        "document_content_hash": CONTENT_HASH,
                        "requirement_unit_id": f"ru_{'3' * 64}",
                    }
                ],
                "out_of_scope_examples": [],
            }
        ),
        TaxonomySearchConcept.model_validate(
            {
                "taxonomy_version_id": str(TAXONOMY_VERSION_ID),
                "concept_id": str(INACTIVE_CONCEPT_ID),
                "stable_key": "legacy.filter",
                "node_type": "capability",
                "node_status": "deprecated",
                "display_name": "旧筛选",
                "aliases": [],
                "definition": "已废弃。",
                "scope_note": "不再使用。",
                "in_scope_examples": [],
                "out_of_scope_examples": [],
            }
        ),
    ]


def _unit(
    statement: str,
    *,
    title: str | None = None,
    quote: str | None = None,
) -> RequirementUnit:
    source_ref = "prd:商品管理 §5.4"
    quote = quote or statement
    return RequirementUnit(
        unit_id=build_requirement_unit_id(
            document_content_hash=CONTENT_HASH,
            source_ref=source_ref,
            statement=statement,
        ),
        system_id=SYSTEM_ID,
        document_id=DOCUMENT_ID,
        document_content_hash=CONTENT_HASH,
        source_ref=source_ref,
        source_quote=quote,
        source_quote_hash=build_source_quote_hash(quote),
        structural_key="product.requirement",
        title=title or statement,
        statement=statement,
        observable_outcome=statement,
        scope_status="atomic",
    )


def _vector_for(text: str) -> list[float]:
    if "单个新建商品" in text:
        return [0.0, 0.0, 1.0]
    if any(token in text for token in ("筛选", "排序", "过滤", "重置")):
        return [0.0, 1.0, 0.0]
    if any(token in text for token in ("同步", "拉取", "商品库")):
        return [1.0, 0.0, 0.0]
    return [0.1, 0.1, 0.1]


async def _embed_batch(texts: Sequence[str]) -> list[list[float]]:
    return [_vector_for(text) for text in texts]


async def test_index_uses_positive_semantics_but_keeps_negative_examples_separate() -> None:
    index = await TaxonomyCandidateRetriever(
        embed_batch=_embed_batch,
        embedding_revision="embedding@1",
    ).build_index(
        taxonomy_version_id=TAXONOMY_VERSION_ID,
        taxonomy_manifest_hash=MANIFEST_HASH,
        concepts=_concepts(),
        policy=_policy(),
    )

    assert [entry.concept.stable_key for entry in index.entries] == ["asset.filter", "product.sync"]
    sync = next(entry for entry in index.entries if entry.concept.stable_key == "product.sync")
    assert "5.4" not in sync.search_text
    assert "商品同步" in sync.search_text
    assert "巨量商品同步" in sync.search_text
    assert "从巨量平台拉取商品数据" in sync.search_text
    assert "只负责同步与状态更新" in sync.search_text
    assert "商品库每天从巨量平台同步" in sync.search_text
    assert "点击按钮单个新建商品" not in sync.search_text
    assert len(sync.out_of_scope_vectors) == 1
    assert index.embedding_revision == "embedding@1"
    assert index.retriever_revision == "taxonomy-candidate-retriever@1"
    assert index.taxonomy_manifest_hash == MANIFEST_HASH


def test_active_capability_requires_positive_requirement_evidence() -> None:
    payload = _concepts()[0].model_dump(mode="json")
    payload["in_scope_examples"] = []

    with pytest.raises(ValidationError, match="active_capability_in_scope_example_required"):
        TaxonomySearchConcept.model_validate(payload)


async def test_index_rejects_cross_version_source_even_when_policy_would_filter_it() -> None:
    concepts = _concepts()
    concepts[-1] = concepts[-1].model_copy(update={"taxonomy_version_id": UUID("99999999-9999-9999-9999-999999999999")})

    with pytest.raises(TaxonomyRetrievalError, match="taxonomy_index_version_mismatch"):
        await TaxonomyCandidateRetriever(
            embed_batch=_embed_batch,
            embedding_revision="embedding@1",
        ).build_index(
            taxonomy_version_id=TAXONOMY_VERSION_ID,
            taxonomy_manifest_hash=MANIFEST_HASH,
            concepts=concepts,
            policy=_policy(),
        )


async def test_retriever_ranks_semantically_matching_active_concept() -> None:
    retriever = TaxonomyCandidateRetriever(embed_batch=_embed_batch, embedding_revision="embedding@1")
    index = await retriever.build_index(
        taxonomy_version_id=TAXONOMY_VERSION_ID,
        taxonomy_manifest_hash=MANIFEST_HASH,
        concepts=_concepts(),
        policy=_policy(),
    )

    candidates = await retriever.retrieve(
        _unit("素材列表支持重置筛选条件并按创建时间排序。", title="筛选与排序"),
        index=index,
        policy=_policy(),
    )

    assert candidates[0].concept_id == FILTER_CONCEPT_ID
    assert candidates[0].rank == 1
    assert candidates[0].score == 1.0
    assert "display_name_exact" in candidates[0].evidence
    assert INACTIVE_CONCEPT_ID not in {candidate.concept_id for candidate in candidates}


async def test_out_of_scope_example_is_a_hard_conflict_not_positive_similarity() -> None:
    retriever = TaxonomyCandidateRetriever(embed_batch=_embed_batch, embedding_revision="embedding@1")
    index = await retriever.build_index(
        taxonomy_version_id=TAXONOMY_VERSION_ID,
        taxonomy_manifest_hash=MANIFEST_HASH,
        concepts=[_concepts()[0]],
        policy=_policy(),
    )

    candidates = await retriever.retrieve(
        _unit("系统支持点击按钮单个新建商品。"),
        index=index,
        policy=_policy(),
    )

    assert len(candidates) == 1
    assert candidates[0].scope_conflict is True
    assert candidates[0].scope_conflict_evidence == [f"negative_example:ru_{'2' * 64}"]
    assert "out_of_scope_conflict" in candidates[0].evidence


async def test_short_generic_query_does_not_reverse_match_a_long_negative_example() -> None:
    async def no_semantic_conflict(texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            if "单个新建商品" in text:
                vectors.append([0.0, 0.0, 1.0])
            elif "商品同步" in text:
                vectors.append([1.0, 0.0, 0.0])
            else:
                vectors.append([0.0, 1.0, 0.0])
        return vectors

    retriever = TaxonomyCandidateRetriever(
        embed_batch=no_semantic_conflict,
        embedding_revision="embedding@1",
    )
    index = await retriever.build_index(
        taxonomy_version_id=TAXONOMY_VERSION_ID,
        taxonomy_manifest_hash=MANIFEST_HASH,
        concepts=[_concepts()[0]],
        policy=_policy(),
    )

    candidates = await retriever.retrieve(_unit("商品"), index=index, policy=_policy())

    assert candidates[0].scope_conflict is False


async def test_candidate_order_is_deterministic_when_scores_tie() -> None:
    async def tied_embeddings(texts: Sequence[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]

    retriever = TaxonomyCandidateRetriever(embed_batch=tied_embeddings, embedding_revision="embedding@1")
    index = await retriever.build_index(
        taxonomy_version_id=TAXONOMY_VERSION_ID,
        taxonomy_manifest_hash=MANIFEST_HASH,
        concepts=list(reversed(_concepts()[:2])),
        policy=_policy(),
    )

    candidates = await retriever.retrieve(_unit("无明显词法命中"), index=index, policy=_policy())

    assert [candidate.stable_key for candidate in candidates] == ["asset.filter", "product.sync"]
    assert [candidate.rank for candidate in candidates] == [1, 2]


@pytest.mark.parametrize("failure", ["exception", "count", "dimension", "non_finite"])
async def test_embedding_failures_are_normalized_to_fail_closed_error(failure: str) -> None:
    async def broken_embeddings(texts: Sequence[str]) -> list[list[float]]:
        if failure == "exception":
            raise TimeoutError("vendor detail must not escape")
        if failure == "count":
            return []
        if failure == "dimension":
            return [[1.0, 0.0] if index == 0 else [1.0] for index, _ in enumerate(texts)]
        return [[float("nan"), 0.0] for _ in texts]

    retriever = TaxonomyCandidateRetriever(embed_batch=broken_embeddings, embedding_revision="embedding@1")

    with pytest.raises(TaxonomyRetrievalError, match="embedding_") as exc_info:
        await retriever.build_index(
            taxonomy_version_id=TAXONOMY_VERSION_ID,
            taxonomy_manifest_hash=MANIFEST_HASH,
            concepts=_concepts()[:2],
            policy=_policy(),
        )

    assert "vendor detail" not in str(exc_info.value)


async def test_index_identity_changes_with_embedding_revision() -> None:
    first = await TaxonomyCandidateRetriever(
        embed_batch=_embed_batch,
        embedding_revision="embedding@1",
    ).build_index(
        taxonomy_version_id=TAXONOMY_VERSION_ID,
        taxonomy_manifest_hash=MANIFEST_HASH,
        concepts=_concepts()[:2],
        policy=_policy(),
    )
    second = await TaxonomyCandidateRetriever(
        embed_batch=_embed_batch,
        embedding_revision="embedding@2",
    ).build_index(
        taxonomy_version_id=TAXONOMY_VERSION_ID,
        taxonomy_manifest_hash=MANIFEST_HASH,
        concepts=_concepts()[:2],
        policy=_policy(),
    )

    assert first.index_hash != second.index_hash
    assert len(first.index_hash) == hashlib.sha256().digest_size * 2


async def test_index_identity_binds_actual_embedding_artifact() -> None:
    async def changed_embeddings(texts: Sequence[str]) -> list[list[float]]:
        return [[*reversed(_vector_for(text))] for text in texts]

    first = await TaxonomyCandidateRetriever(
        embed_batch=_embed_batch,
        embedding_revision="embedding@1",
    ).build_index(
        taxonomy_version_id=TAXONOMY_VERSION_ID,
        taxonomy_manifest_hash=MANIFEST_HASH,
        concepts=_concepts()[:2],
        policy=_policy(),
    )
    changed = await TaxonomyCandidateRetriever(
        embed_batch=changed_embeddings,
        embedding_revision="embedding@1",
    ).build_index(
        taxonomy_version_id=TAXONOMY_VERSION_ID,
        taxonomy_manifest_hash=MANIFEST_HASH,
        concepts=_concepts()[:2],
        policy=_policy(),
    )

    assert first.index_hash != changed.index_hash


async def test_index_identity_ignores_resolution_only_policy_changes() -> None:
    retriever = TaxonomyCandidateRetriever(embed_batch=_embed_batch, embedding_revision="embedding@1")
    first = await retriever.build_index(
        taxonomy_version_id=TAXONOMY_VERSION_ID,
        taxonomy_manifest_hash=MANIFEST_HASH,
        concepts=_concepts()[:2],
        policy=_policy(),
    )
    changed_resolution_policy = await retriever.build_index(
        taxonomy_version_id=TAXONOMY_VERSION_ID,
        taxonomy_manifest_hash=MANIFEST_HASH,
        concepts=_concepts()[:2],
        policy=_policy(minimum_score=0.7, model_revision="resolver@2"),
    )

    assert first.index_hash == changed_resolution_policy.index_hash


async def test_candidate_source_binding_cannot_drift_from_index_identity() -> None:
    retriever = TaxonomyCandidateRetriever(embed_batch=_embed_batch, embedding_revision="embedding@1")
    policy = _policy()
    index = await retriever.build_index(
        taxonomy_version_id=TAXONOMY_VERSION_ID,
        taxonomy_manifest_hash=MANIFEST_HASH,
        concepts=_concepts()[:2],
        policy=policy,
    )

    binding = retriever.bind(index=index, policy=policy)
    candidates = await binding.retrieve_candidates(_unit("商品库从巨量平台同步商品。"))

    assert binding.candidate_index_hash == index.index_hash
    assert binding.taxonomy_version_id == TAXONOMY_VERSION_ID
    assert binding.taxonomy_manifest_hash == MANIFEST_HASH
    assert binding.policy_version == policy.canonical_hash
    assert candidates[0].concept_id == SYNC_CONCEPT_ID

    rebound = retriever.bind(index=index, policy=_policy(minimum_score=0.7))
    assert rebound.candidate_index_hash == index.index_hash
    assert rebound.policy_version != binding.policy_version

    with pytest.raises(TaxonomyRetrievalError, match="taxonomy_index_policy_mismatch"):
        retriever.bind(index=index, policy=_policy(allowed_node_types=["module"]))
