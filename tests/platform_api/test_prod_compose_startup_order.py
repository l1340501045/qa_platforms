from pathlib import Path

import yaml


def test_worker_waits_for_api_migrations_before_starting() -> None:
    compose_path = Path(__file__).resolve().parents[2] / "docker-compose.prod.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))

    assert compose["services"]["worker"]["depends_on"]["api"]["condition"] == "service_healthy"
