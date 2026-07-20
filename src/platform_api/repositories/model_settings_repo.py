"""AI 模型配置版本的数据访问层。"""

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.models.model_settings import AIModelConfigEntry, AIModelConfigState, AIModelConfigVersion


@dataclass(frozen=True)
class StoredModelVersion:
    version: AIModelConfigVersion
    entries: tuple[AIModelConfigEntry, ...]


class ModelSettingsRepository:
    """只负责配置版本的查询、插入和有效指针切换。"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_state(self, *, for_update: bool = False) -> AIModelConfigState | None:
        stmt = select(AIModelConfigState).where(AIModelConfigState.id == 1)
        if for_update:
            # 同一 session 在连接测试前已读取过 state。加锁后二次查询必须覆盖
            # identity map 中的旧 revision，才能可靠发现测试期间发生的并发保存。
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_version(self, version_id: UUID) -> StoredModelVersion | None:
        version_result = await self.session.execute(
            select(AIModelConfigVersion).where(AIModelConfigVersion.id == version_id)
        )
        version = version_result.scalar_one_or_none()
        if version is None:
            return None

        entry_result = await self.session.execute(
            select(AIModelConfigEntry)
            .where(AIModelConfigEntry.version_id == version_id)
            .order_by(AIModelConfigEntry.model_role)
        )
        return StoredModelVersion(version=version, entries=tuple(entry_result.scalars().all()))

    async def get_active_version(
        self,
        *,
        for_update: bool = False,
    ) -> tuple[AIModelConfigState | None, StoredModelVersion | None]:
        state = await self.get_state(for_update=for_update)
        if state is None or state.active_version_id is None:
            return state, None
        return state, await self.get_version(state.active_version_id)

    async def add_version(
        self,
        version: AIModelConfigVersion,
        entries: list[AIModelConfigEntry],
    ) -> None:
        self.session.add(version)
        await self.session.flush()
        self.session.add_all(entries)
        await self.session.flush()

    async def activate(self, state: AIModelConfigState, version: AIModelConfigVersion) -> None:
        state.active_version_id = version.id
        state.revision = version.revision
        state.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
