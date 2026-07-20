import uuid

from sqlalchemy import CheckConstraint, UniqueConstraint

from src.platform_api.models.model_settings import (
    AIModelConfigEntry,
    AIModelConfigState,
    AIModelConfigVersion,
)
from src.platform_api.models.public import Base
from src.platform_api.models.testcase import TestBatch as BatchModel


def test_model_settings_tables_are_registered_without_permanent_batch_version_lock() -> None:
    assert "public.ai_model_config_versions" in Base.metadata.tables
    assert "public.ai_model_config_entries" in Base.metadata.tables
    assert "public.ai_model_config_state" in Base.metadata.tables

    assert "model_config_version_id" not in BatchModel.__table__.c


def test_model_config_entry_restricts_roles_and_keeps_ciphertext_out_of_repr() -> None:
    role_checks = {
        constraint.name
        for constraint in AIModelConfigEntry.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    entry = AIModelConfigEntry(
        id=uuid.uuid4(),
        version_id=uuid.uuid4(),
        model_role="vision",
        base_url="https://vision.example/v1",
        model_name="vision-model",
        api_key_ciphertext="encrypted-provider-key",
        source="database",
        validation_status="passed",
    )

    assert "ck_ai_model_config_entries_role" in role_checks
    assert "encrypted-provider-key" not in repr(entry)


def test_model_settings_state_is_a_singleton_contract() -> None:
    state_checks = {
        constraint.name
        for constraint in AIModelConfigState.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }

    revision_unique_constraints = {
        constraint.name
        for constraint in AIModelConfigVersion.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert "ck_ai_model_config_state_singleton" in state_checks
    assert "uq_ai_model_config_versions_revision" in revision_unique_constraints
