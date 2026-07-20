import logging
from types import SimpleNamespace

from src.platform_api.core import database
from src.platform_api.core.exceptions import unhandled_error_handler


async def test_unhandled_exception_log_omits_exception_body(caplog) -> None:
    request = SimpleNamespace(
        url=SimpleNamespace(path="/api/v1/settings/ai-models/vision"),
        state=SimpleNamespace(request_id="request-123"),
    )
    caplog.set_level(logging.ERROR)

    response = await unhandled_error_handler(
        request,
        RuntimeError("provider-secret gAAAA-ciphertext raw-response"),
    )

    assert response.status_code == 500
    assert "RuntimeError" in caplog.text
    assert "request-123" in caplog.text
    assert "provider-secret" not in caplog.text
    assert "gAAAA-ciphertext" not in caplog.text
    assert "raw-response" not in caplog.text


def test_database_engine_hides_bound_parameters(monkeypatch) -> None:
    captured = {}
    fake_engine = object()

    def fake_create_async_engine(url, **kwargs):
        captured.update(kwargs)
        return fake_engine

    database.reset_engine()
    monkeypatch.delenv("QA_WORKER_MODE", raising=False)
    monkeypatch.setattr(database, "create_async_engine", fake_create_async_engine)
    try:
        assert database.get_engine() is fake_engine
    finally:
        database.reset_engine()

    assert captured["hide_parameters"] is True
