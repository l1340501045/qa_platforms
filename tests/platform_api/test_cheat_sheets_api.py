"""cheat sheet 极简审核 REST API 测试。"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from src.knowledge_base.repositories.cheat_sheet_repo import CheatSheetRepository
from src.knowledge_base.schemas.cheat_sheet import CheatSheetItemCreate
from src.platform_api.core.database import get_session_factory
from src.platform_api.main import app
from src.platform_api.models.enums import CheatSheetType
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
async def client():
    """HTTPX async client for testing FastAPI app。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _seed_sheet(items: list[CheatSheetItemCreate]):
    system_id = uuid.uuid4()
    document_id = uuid.uuid4()
    factory = get_session_factory()
    async with factory() as session:
        session.add(System(id=system_id, name=f"cheat_api_{system_id.hex[:8]}"))
        await session.flush()
        session.add(
            Document(
                id=document_id,
                system_id=system_id,
                title="cheat sheet api 测试文档",
                doc_type="prd",
                content="content",
                storage_path="/test/cheat-sheet-api.md",
                content_hash=uuid.uuid4().hex,
            )
        )
        await session.flush()
        sheet = await CheatSheetRepository(session).save_sheet(document_id, system_id, items)
        item_models = await CheatSheetRepository(session).list_items(sheet.id)
        await session.commit()
    return document_id, sheet.id, [item.id for item in item_models]


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
async def test_list_and_get_cheat_sheet_items(client: AsyncClient):
    """GET list 支持 type/status 筛选，GET detail 返回条目详情。"""
    document_id, _, item_ids = await _seed_sheet(
        [
            _item(CheatSheetType.CONFUSION_PAIR, "监测链接 vs 投放链接", "must"),
            _item(CheatSheetType.MUST_TEST, "批量必测", "batch"),
        ]
    )

    resp = await client.get(
        f"/api/v1/documents/{document_id}/cheat-sheets",
        params={"type": "confusion_pair", "status": "pending", "page": 1, "per_page": 10},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["title"] == "监测链接 vs 投放链接"
    assert data["items"][0]["review_status"] == "pending"

    detail_resp = await client.get(f"/api/v1/cheat-sheets/{item_ids[0]}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()["data"]
    assert detail["id"] == str(item_ids[0])
    assert detail["sheet_type"] == "confusion_pair"


@pytest.mark.asyncio
async def test_edit_and_review_cheat_sheet_item(client: AsyncClient):
    """PATCH edit 写 qa_content；PATCH review 用 status 字段 approve/reject。"""
    _, _, item_ids = await _seed_sheet([_item(CheatSheetType.CONFUSION_PAIR, "IAP vs IAA", "must")])
    item_id = item_ids[0]

    edit_resp = await client.patch(
        f"/api/v1/cheat-sheets/{item_id}",
        json={"qa_content": {"item_a": "QA IAP", "item_b": "QA IAA"}},
    )
    assert edit_resp.status_code == 200
    edited = edit_resp.json()["data"]
    assert edited["qa_content"] == {"item_a": "QA IAP", "item_b": "QA IAA"}
    assert edited["review_status"] == "pending"

    approve_resp = await client.patch(
        f"/api/v1/cheat-sheets/{item_id}/review",
        json={"status": "approved", "by": "qa_lead"},
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json()["data"]["review_status"] == "approved"

    reject_resp = await client.patch(
        f"/api/v1/cheat-sheets/{item_id}/review",
        json={"status": "rejected", "comment": "概念不准确", "by": "qa_lead"},
    )
    assert reject_resp.status_code == 200
    rejected = reject_resp.json()["data"]
    assert rejected["review_status"] == "rejected"
    assert rejected["review_comment"] == "概念不准确"


@pytest.mark.asyncio
async def test_batch_approve_cheat_sheet_items(client: AsyncClient):
    """POST batch-approve 批量通过指定 sheet_type/tier。"""
    document_id, _, _ = await _seed_sheet(
        [
            _item(CheatSheetType.MUST_TEST, "批量必测1", "batch"),
            _item(CheatSheetType.MUST_TEST, "批量必测2", "batch"),
            _item(CheatSheetType.CONFUSION_PAIR, "必审易混", "must"),
        ]
    )

    resp = await client.post(
        f"/api/v1/documents/{document_id}/cheat-sheets/batch-approve",
        json={"sheet_type": "must_test", "tier": "batch", "by": "qa_lead"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["updated_count"] == 2

    list_resp = await client.get(
        f"/api/v1/documents/{document_id}/cheat-sheets",
        params={"type": "must_test", "status": "approved"},
    )
    assert list_resp.status_code == 200
    assert list_resp.json()["data"]["total"] == 2
