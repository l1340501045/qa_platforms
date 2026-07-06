from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType


def _load_preflight() -> ModuleType:
    module_path = Path(__file__).parents[1] / "scripts" / "ux_acceptance_preflight.py"
    spec = importlib.util.spec_from_file_location("ux_acceptance_preflight", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _completed_branch(branch: str):
    return subprocess.CompletedProcess(
        ["git", "branch", "--show-current"],
        0,
        stdout=f"{branch}\n",
        stderr="",
    )


def test_check_branch_allows_main_after_stage_merge(monkeypatch):
    preflight = _load_preflight()
    monkeypatch.setattr(preflight, "_run", lambda args: _completed_branch("main"))

    result = preflight.check_branch()

    assert result.ok is True
    assert result.detail == "main"


def test_check_branch_keeps_stage_branch_allowed(monkeypatch):
    preflight = _load_preflight()
    monkeypatch.setattr(
        preflight,
        "_run",
        lambda args: _completed_branch("feat/qa-platform-ux-modernization"),
    )

    result = preflight.check_branch()

    assert result.ok is True
    assert result.detail == "feat/qa-platform-ux-modernization"


def test_check_branch_rejects_unrelated_branch(monkeypatch):
    preflight = _load_preflight()
    monkeypatch.setattr(preflight, "_run", lambda args: _completed_branch("wip/demo"))

    result = preflight.check_branch()

    assert result.ok is False
    assert "main" in result.fix
    assert "feat/qa-platform-ux-modernization" in result.fix


def test_parse_frontend_generation_config(tmp_path: Path):
    preflight = _load_preflight()
    frontend = tmp_path / "batchApi.ts"
    frontend.write_text(
        """
export const BEST_PRACTICE_GENERATION_CONFIG = {
  quality_profile: 'best_practice_default_2026_07',
  split_cap_enabled: true,
  existence_merge_enabled: true,
  cases_per_tp_cap: 4,
  p0_quota_enabled: false,
  p0_quota: 0.3,
};
""",
        encoding="utf-8",
    )

    parsed = preflight._parse_frontend_generation_config(frontend)

    assert parsed["quality_profile"] == "best_practice_default_2026_07"
    assert parsed["split_cap_enabled"] is True
    assert parsed["existence_merge_enabled"] is True
    assert parsed["cases_per_tp_cap"] == 4
    assert parsed["p0_quota_enabled"] is False
    assert parsed["p0_quota"] == 0.3


def test_parse_pipeline_generation_config(tmp_path: Path):
    preflight = _load_preflight()
    pipeline = tmp_path / "config.py"
    pipeline.write_text(
        """
from typing import Any

BEST_PRACTICE_GENERATION_CONFIG: dict[str, Any] = {
    "split_cap_enabled": True,
    "existence_merge_enabled": True,
    "cases_per_tp_cap": 4,
    "p0_quota_enabled": False,
}
""",
        encoding="utf-8",
    )

    parsed = preflight._parse_pipeline_generation_config(pipeline)

    assert parsed == {
        "split_cap_enabled": True,
        "existence_merge_enabled": True,
        "cases_per_tp_cap": 4,
        "p0_quota_enabled": False,
    }


def test_parse_settings_generation_defaults(tmp_path: Path):
    preflight = _load_preflight()
    settings = tmp_path / "settings.py"
    settings.write_text(
        """
class Settings:
    split_cap_enabled: bool = True
    cases_per_tp_cap: int = 4
    existence_merge_enabled: bool = True
    p0_quota_enabled: bool = False
    p0_quota: float = 0.30
""",
        encoding="utf-8",
    )

    parsed = preflight._parse_settings_generation_defaults(settings)

    assert parsed == {
        "existence_merge_enabled": True,
        "split_cap_enabled": True,
        "cases_per_tp_cap": 4,
        "p0_quota_enabled": False,
    }


def test_check_generation_config_passes_for_matching_files(tmp_path: Path, monkeypatch):
    preflight = _load_preflight()
    (tmp_path / "web/src/services").mkdir(parents=True)
    (tmp_path / "src/testcase_generator/pipeline").mkdir(parents=True)
    (tmp_path / "src/platform_api/core").mkdir(parents=True)
    (tmp_path / "web/src/services/batchApi.ts").write_text(
        """
export const BEST_PRACTICE_GENERATION_CONFIG = {
  split_cap_enabled: true,
  existence_merge_enabled: true,
  cases_per_tp_cap: 4,
  p0_quota_enabled: false,
};
""",
        encoding="utf-8",
    )
    (tmp_path / "src/testcase_generator/pipeline/config.py").write_text(
        """
BEST_PRACTICE_GENERATION_CONFIG: dict[str, object] = {
    "split_cap_enabled": True,
    "existence_merge_enabled": True,
    "cases_per_tp_cap": 4,
    "p0_quota_enabled": False,
}
""",
        encoding="utf-8",
    )
    (tmp_path / "src/platform_api/core/settings.py").write_text(
        """
class Settings:
    split_cap_enabled: bool = True
    cases_per_tp_cap: int = 4
    existence_merge_enabled: bool = True
    p0_quota_enabled: bool = False
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(preflight, "ROOT", tmp_path)

    result = preflight.check_generation_config()

    assert result.ok is True
    assert "cases_per_tp_cap=4" in result.detail


def test_check_generation_config_fails_for_mismatch(tmp_path: Path, monkeypatch):
    preflight = _load_preflight()
    (tmp_path / "web/src/services").mkdir(parents=True)
    (tmp_path / "src/testcase_generator/pipeline").mkdir(parents=True)
    (tmp_path / "src/platform_api/core").mkdir(parents=True)
    (tmp_path / "web/src/services/batchApi.ts").write_text(
        """
export const BEST_PRACTICE_GENERATION_CONFIG = {
  split_cap_enabled: true,
  existence_merge_enabled: true,
  cases_per_tp_cap: 3,
  p0_quota_enabled: false,
};
""",
        encoding="utf-8",
    )
    (tmp_path / "src/testcase_generator/pipeline/config.py").write_text(
        """
BEST_PRACTICE_GENERATION_CONFIG: dict[str, object] = {
    "split_cap_enabled": True,
    "existence_merge_enabled": True,
    "cases_per_tp_cap": 4,
    "p0_quota_enabled": False,
}
""",
        encoding="utf-8",
    )
    (tmp_path / "src/platform_api/core/settings.py").write_text(
        """
class Settings:
    split_cap_enabled: bool = True
    cases_per_tp_cap: int = 4
    existence_merge_enabled: bool = True
    p0_quota_enabled: bool = False
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(preflight, "ROOT", tmp_path)

    result = preflight.check_generation_config()

    assert result.ok is False
    assert "frontend.cases_per_tp_cap=3，期望 4" in result.detail
