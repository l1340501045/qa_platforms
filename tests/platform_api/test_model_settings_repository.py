import uuid

from src.platform_api.models.model_settings import AIModelConfigEntry, AIModelConfigVersion
from src.platform_api.repositories.model_settings_repo import ModelSettingsRepository


class _Result:
    def scalar_one_or_none(self):
        return None


class _RecordingSession:
    def __init__(self):
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return _Result()


async def test_locked_state_query_refreshes_identity_map_values() -> None:
    """连接测试期间若别人已保存，FOR UPDATE 必须读到提交后的 revision。"""

    session = _RecordingSession()
    repository = ModelSettingsRepository(session)  # type: ignore[arg-type]

    await repository.get_state(for_update=True)

    assert session.statement is not None
    assert session.statement.get_execution_options().get("populate_existing") is True


class _WriteOrderSession:
    def __init__(self):
        self.events: list[tuple[str, object | None]] = []

    def add(self, value):
        self.events.append(("add", type(value)))

    def add_all(self, values):
        self.events.append(("add_all", tuple(type(value) for value in values)))

    async def flush(self):
        self.events.append(("flush", None))


async def test_add_version_flushes_parent_before_entries() -> None:
    """entry 通过 UUID 外键关联版本，必须先落主记录再写子记录。"""

    version_id = uuid.uuid4()
    version = AIModelConfigVersion(id=version_id, revision=1)
    entry = AIModelConfigEntry(
        id=uuid.uuid4(),
        version_id=version_id,
        model_role="primary",
        base_url="https://primary.example/v1",
        model_name="primary-model",
        source="database",
        validation_status="passed",
    )
    session = _WriteOrderSession()
    repository = ModelSettingsRepository(session)  # type: ignore[arg-type]

    await repository.add_version(version, [entry])

    assert session.events == [
        ("add", AIModelConfigVersion),
        ("flush", None),
        ("add_all", (AIModelConfigEntry,)),
        ("flush", None),
    ]
