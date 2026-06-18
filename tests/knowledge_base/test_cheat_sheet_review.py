"""cheat sheet 审核 service 测试：状态机 + 分级 + 批量采纳。"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.knowledge_base.repositories.cheat_sheet_repo import CheatSheetRepository
from src.knowledge_base.schemas.cheat_sheet import CheatSheetItemCreate
from src.knowledge_base.services.cheat_sheet.review_service import CheatSheetReviewService
from src.platform_api.core.database import get_session_factory
from src.platform_api.models.enums import CheatSheetReviewStatus, CheatSheetType
from src.platform_api.models.knowledge import Document
from src.platform_api.models.public import System
from tests.platform_api.conftest import requires_db

pytestmark = requires_db


@pytest.fixture(autouse=True)
def reset_db_engine_per_test():
    """每个测试前后重置全局 engine，避免 asyncpg 连接跨 event loop 复用。"""
    from src.platform_api.core.database import reset_engine

    reset_engine()
    yield
    reset_engine()


@pytest.fixture
async def db_session():
    """获取真实 DB session。"""
    factory = get_session_factory()
    async with factory() as session:
        yield session
        await session.rollback()


async def _seed_document(db_session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    system_id = uuid.uuid4()
    document_id = uuid.uuid4()
    db_session.add(System(id=system_id, name=f"cheat_review_{system_id.hex[:8]}"))
    await db_session.flush()
    db_session.add(
        Document(
            id=document_id,
            system_id=system_id,
            title="cheat sheet review 测试文档",
            doc_type="prd",
            content="content",
            storage_path="/test/cheat-sheet-review.md",
            content_hash=uuid.uuid4().hex,
        )
    )
    await db_session.flush()
    return document_id, system_id


def _item(sheet_type: CheatSheetType, title: str, review_tier: str) -> CheatSheetItemCreate:
    return CheatSheetItemCreate(
        sheet_type=sheet_type,
        title=title,
        ai_content={"title": title},
        review_tier=review_tier,
        source_entity_ids=[],
        source_relation_ids=[],
        source_section_refs=[],
    )


@pytest.mark.asyncio
async def test_approve_reject_and_edit_update_review_state(db_session: AsyncSession):
    """approve/reject/edit 写审核状态与 QA 内容，edit 非 pending 时转回 pending。"""
    document_id, system_id = await _seed_document(db_session)
    repo = CheatSheetRepository(db_session)
    sheet = await repo.save_sheet(
        document_id,
        system_id,
        [_item(CheatSheetType.CONFUSION_PAIR, "监测链接 vs 投放链接", "must")],
    )
    item = (await repo.list_items(sheet.id))[0]
    service = CheatSheetReviewService(db_session)

    approved = await service.approve(item.id, by="qa_lead")
    assert approved.review_status == CheatSheetReviewStatus.APPROVED
    assert approved.reviewed_by == "qa_lead"
    assert approved.reviewed_at is not None

    edited = await service.edit(item.id, qa_content={"item_a": "QA监测链接"})
    assert edited.ai_content == {"title": "监测链接 vs 投放链接"}
    assert edited.qa_content == {"item_a": "QA监测链接"}
    assert edited.review_status == CheatSheetReviewStatus.PENDING

    rejected = await service.reject(item.id, comment="概念不准确", by="qa_lead")
    assert rejected.review_status == CheatSheetReviewStatus.REJECTED
    assert rejected.review_comment == "概念不准确"
    assert rejected.reviewed_by == "qa_lead"


@pytest.mark.asyncio
async def test_batch_approve_and_list_pending_must_review(db_session: AsyncSession):
    """批量采纳只处理匹配类型/档位的 pending，must-review 列表只返回 must+pending。"""
    document_id, system_id = await _seed_document(db_session)
    repo = CheatSheetRepository(db_session)
    sheet = await repo.save_sheet(
        document_id,
        system_id,
        [
            _item(CheatSheetType.MUST_TEST, "批量必测1", "batch"),
            _item(CheatSheetType.MUST_TEST, "批量必测2", "batch"),
            _item(CheatSheetType.CONFUSION_PAIR, "必审易混", "must"),
        ],
    )
    service = CheatSheetReviewService(db_session)

    pending_must = await service.list_pending_must_review(sheet.id)
    assert [item.title for item in pending_must] == ["必审易混"]

    updated_count = await service.batch_approve(
        sheet.id,
        sheet_type=CheatSheetType.MUST_TEST,
        tier="batch",
        by="qa_lead",
    )

    assert updated_count == 2
    approved_must_tests = await repo.list_items(
        sheet.id,
        sheet_type=CheatSheetType.MUST_TEST,
        review_status=CheatSheetReviewStatus.APPROVED,
    )
    assert [item.title for item in approved_must_tests] == ["批量必测1", "批量必测2"]
    assert [item.title for item in await service.list_pending_must_review(sheet.id)] == ["必审易混"]
