from __future__ import annotations

from argparse import Namespace
from types import SimpleNamespace
from uuid import UUID

import pytest

from scripts import taxonomy_replay


class _SessionContext:
    async def __aenter__(self):
        return SimpleNamespace()

    async def __aexit__(self, exc_type, exc, traceback):
        return False


@pytest.mark.asyncio
async def test_apply_reports_recovery_receipt_for_non_os_artifact_failure(monkeypatch, capsys) -> None:
    run_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    assignments = SimpleNamespace(manifest_hash="m" * 64, taxonomy_version=1)
    manifest = SimpleNamespace(version=1)
    result = SimpleNamespace(
        applied=True,
        run_id=run_id,
        source_scope="database",
        baseline_hash="b" * 64,
        plan_hash="p" * 64,
        overall_coverage=1.0,
        main_coverage=1.0,
        unresolved_count=0,
    )

    class _ReplayService:
        def __init__(self, session):
            self.session = session

        async def replay(self, *args, **kwargs):
            return result

    monkeypatch.setattr(taxonomy_replay, "get_session_factory", lambda: _SessionContext)
    monkeypatch.setattr(taxonomy_replay, "load_assignment_set", lambda path: assignments)
    monkeypatch.setattr(taxonomy_replay, "load_manifest", lambda path: manifest)
    monkeypatch.setattr(taxonomy_replay, "manifest_hash", lambda value: assignments.manifest_hash)
    monkeypatch.setattr(taxonomy_replay, "TaxonomyReplayService", _ReplayService)
    monkeypatch.setattr(taxonomy_replay, "_preflight_apply_output", lambda path: None)
    monkeypatch.setattr(
        taxonomy_replay,
        "write_replay_artifacts",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("report rendering failed")),
    )
    args = Namespace(
        command="replay",
        assignments=SimpleNamespace(),
        manifest=SimpleNamespace(),
        output_dir=SimpleNamespace(),
        apply=True,
        expected_baseline_hash="b" * 64,
        expected_plan_hash="p" * 64,
        expected_anomaly_case_ids=None,
        actor="reviewer",
    )

    exit_code = await taxonomy_replay._run_async(args)

    captured = capsys.readouterr()
    assert exit_code == 3
    assert "database_committed_artifact_write_failed" in captured.err
    assert str(run_id) in captured.err
    assert "rollback" in captured.err
