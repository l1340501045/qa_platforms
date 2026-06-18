"""cheat sheet repo 测试：版本化保存 + 审核裁定保留 + 注入查询"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.knowledge_base.repositories.cheat_sheet_repo import CheatSheetRepository
from src.knowledge_base.schemas.cheat_sheet import CheatSheetItemCreate
from src.platform_api.core.database import get_session_factory
from src.platform_api.models.enums import CheatSheetReviewStatus, CheatSheetType
from src.platform_api.models.knowledge import CheatSheetItem, Document
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
    db_session.add(System(id=system_id, name=f"cheat_sheet_{system_id.hex[:8]}"))
    await db_session.flush()
    db_session.add(
        Document(
            id=document_id,
            system_id=system_id,
            title="cheat sheet repo 测试文档",
            doc_type="prd",
            content="content",
            storage_path="/test/cheat-sheet.md",
            content_hash=uuid.uuid4().hex,
        )
    )
    await db_session.flush()
    return document_id, system_id


def _item(
    *,
    sheet_type: CheatSheetType,
    title: str,
    ai_content: dict,
    dedup_key: str | None = None,
    review_tier: str = "must",
    sort_order: int = 0,
) -> CheatSheetItemCreate:
    return CheatSheetItemCreate(
        sheet_type=sheet_type,
        title=title,
        dedup_key=dedup_key or f"{sheet_type}:{title}",
        ai_content=ai_content,
        review_tier=review_tier,
        source_entity_ids=[str(uuid.uuid4())],
        source_relation_ids=[str(uuid.uuid4())],
        source_section_refs=["§5.1"],
        sort_order=sort_order,
    )


@pytest.mark.asyncio
async def test_save_sheet_creates_new_version_and_preserves_approved_qa_content(db_session: AsyncSession):
    """re-extract 新建 version，但按稳定 dedup_key 匹配旧 approved 条目并保留 QA 裁定。"""
    document_id, system_id = await _seed_document(db_session)
    repo = CheatSheetRepository(db_session)

    first_sheet = await repo.save_sheet(
        document_id,
        system_id,
        [
            _item(
                sheet_type=CheatSheetType.CONFUSION_PAIR,
                title="监测链接 vs 投放链接",
                dedup_key="confusion:concept_monitor_link|concept_delivery_link",
                ai_content={"item_a": "监测链接", "item_b": "投放链接"},
            )
        ],
        source_entity_count=10,
        source_relation_count=3,
    )
    assert first_sheet.version == 1

    first_items = await repo.list_items(first_sheet.id)
    assert len(first_items) == 1
    first_items[0].review_status = CheatSheetReviewStatus.APPROVED
    first_items[0].qa_content = {"item_a": "QA监测链接", "item_b": "QA投放链接"}
    await db_session.flush()

    second_sheet = await repo.save_sheet(
        document_id,
        system_id,
        [
            _item(
                sheet_type=CheatSheetType.CONFUSION_PAIR,
                title="投放链接 / 监测链接 易混对照（LLM 改写标题）",
                dedup_key="confusion:concept_monitor_link|concept_delivery_link",
                ai_content={"item_a": "新AI监测链接", "item_b": "新AI投放链接"},
            ),
            _item(
                sheet_type=CheatSheetType.SECTION_PRIORITY,
                title="局部章节优先于全局默认",
                ai_content={"local_section": "§5.7.1", "global_section": "§5.0.3"},
                sort_order=1,
            ),
        ],
        source_entity_count=20,
        source_relation_count=6,
    )

    assert second_sheet.version == 2
    second_items = await repo.list_items(second_sheet.id)
    by_title = {item.title: item for item in second_items}
    carried = by_title["投放链接 / 监测链接 易混对照（LLM 改写标题）"]
    assert carried.review_status == CheatSheetReviewStatus.APPROVED
    assert carried.qa_content == {"item_a": "QA监测链接", "item_b": "QA投放链接"}
    assert carried.ai_content == {"item_a": "新AI监测链接", "item_b": "新AI投放链接"}
    assert carried.dedup_key == "confusion:concept_monitor_link|concept_delivery_link"
    assert by_title["局部章节优先于全局默认"].review_status == CheatSheetReviewStatus.PENDING


@pytest.mark.asyncio
async def test_list_items_filters_by_type_and_review_status(db_session: AsyncSession):
    """list_items 支持按 sheet_type / review_status 筛选。"""
    document_id, system_id = await _seed_document(db_session)
    repo = CheatSheetRepository(db_session)
    sheet = await repo.save_sheet(
        document_id,
        system_id,
        [
            _item(
                sheet_type=CheatSheetType.CONFUSION_PAIR,
                title="A vs B",
                ai_content={"item_a": "A", "item_b": "B"},
            ),
            _item(
                sheet_type=CheatSheetType.SECTION_PRIORITY,
                title="局部优先",
                ai_content={"local_section": "§2", "global_section": "§1"},
            ),
        ],
    )

    result = await db_session.execute(
        select(CheatSheetItem).where(
            CheatSheetItem.sheet_id == sheet.id,
            CheatSheetItem.sheet_type == CheatSheetType.SECTION_PRIORITY,
        )
    )
    priority_item = result.scalar_one()
    priority_item.review_status = CheatSheetReviewStatus.APPROVED
    await db_session.flush()

    priority_items = await repo.list_items(sheet.id, sheet_type=CheatSheetType.SECTION_PRIORITY)
    approved_items = await repo.list_items(sheet.id, review_status=CheatSheetReviewStatus.APPROVED)

    assert [item.title for item in priority_items] == ["局部优先"]
    assert [item.title for item in approved_items] == ["局部优先"]


@pytest.mark.asyncio
async def test_get_approved_for_injection_returns_latest_version_grouped_by_type(db_session: AsyncSession):
    """注入查询只取最新 version 的 approved 条目，并优先使用 qa_content。"""
    document_id, system_id = await _seed_document(db_session)
    repo = CheatSheetRepository(db_session)
    old_sheet = await repo.save_sheet(
        document_id,
        system_id,
        [
            _item(
                sheet_type=CheatSheetType.CONFUSION_PAIR,
                title="旧条目",
                ai_content={"item_a": "old"},
            )
        ],
    )
    old_items = await repo.list_items(old_sheet.id)
    old_items[0].review_status = CheatSheetReviewStatus.APPROVED
    await db_session.flush()

    latest_sheet = await repo.save_sheet(
        document_id,
        system_id,
        [
            _item(
                sheet_type=CheatSheetType.CONFUSION_PAIR,
                title="新条目",
                ai_content={"item_a": "AI"},
            )
        ],
    )
    latest_items = await repo.list_items(latest_sheet.id)
    latest_items[0].review_status = CheatSheetReviewStatus.APPROVED
    latest_items[0].qa_content = {"item_a": "QA"}
    await db_session.flush()

    approved = await repo.get_approved_for_injection(document_id)

    assert set(approved.keys()) == {CheatSheetType.CONFUSION_PAIR}
    assert len(approved[CheatSheetType.CONFUSION_PAIR]) == 1
    assert approved[CheatSheetType.CONFUSION_PAIR][0].title == "新条目"
    assert approved[CheatSheetType.CONFUSION_PAIR][0].content == {"item_a": "QA"}


@pytest.mark.asyncio
async def test_get_approved_for_injection_keeps_empty_qa_content(db_session: AsyncSession):
    """QA 明确保存 {} 时也应优先注入 QA 版，而不是回退 AI 版。"""
    document_id, system_id = await _seed_document(db_session)
    repo = CheatSheetRepository(db_session)
    sheet = await repo.save_sheet(
        document_id,
        system_id,
        [
            _item(
                sheet_type=CheatSheetType.PRD_STATUS,
                title="待确认文案",
                ai_content={"status_kind": "tbd", "subject": "AI文案"},
            )
        ],
    )
    items = await repo.list_items(sheet.id)
    items[0].review_status = CheatSheetReviewStatus.APPROVED
    items[0].qa_content = {}
    await db_session.flush()

    approved = await repo.get_approved_for_injection(document_id)

    assert approved[CheatSheetType.PRD_STATUS][0].content == {}


@pytest.mark.asyncio
async def test_get_approved_for_injection_returns_empty_dict_without_sheet(db_session: AsyncSession):
    """空库或未提取文档返回 {}，供注入侧安全兜底。"""
    repo = CheatSheetRepository(db_session)

    approved = await repo.get_approved_for_injection(uuid.uuid4())

    assert approved == {}
