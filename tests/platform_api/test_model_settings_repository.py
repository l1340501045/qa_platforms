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
