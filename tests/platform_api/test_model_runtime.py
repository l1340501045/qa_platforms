from src.platform_api.core.model_runtime import (
    ModelConfigBundle,
    ModelEndpointConfig,
    ModelRole,
    build_environment_model_bundle,
    get_current_model_bundle,
    model_runtime_scope,
)
from src.platform_api.core.settings import Settings


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "llm_base_url": "https://primary.example/v1",
        "llm_api_key": "primary-secret",
        "llm_primary_model": "primary-model",
        "llm_vision_base_url": "https://vision.example/v1",
        "llm_vision_api_key": "vision-secret",
        "llm_vision_model": "vision-model",
        "llm_verify_base_url": "https://verify.example/v1",
        "llm_verify_api_key": "verify-secret",
        "llm_verify_model": "verify-model",
        "embedding_base_url": "https://embedding.example/v1",
        "embedding_api_key": "embedding-secret",
        "openai_embedding_model": "embedding-model",
        "openai_api_key": "legacy-secret",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_environment_bundle_resolves_four_independent_routes() -> None:
    bundle = build_environment_model_bundle(_settings())

    primary = bundle.for_role(ModelRole.PRIMARY)
    vision = bundle.for_role(ModelRole.VISION)
    verify = bundle.for_role(ModelRole.VERIFY)
    embedding = bundle.for_role(ModelRole.EMBEDDING)

    assert (primary.base_url, primary.api_key, primary.model_name) == (
        "https://primary.example/v1",
        "primary-secret",
        "primary-model",
    )
    assert (vision.base_url, vision.api_key, vision.model_name) == (
        "https://vision.example/v1",
        "vision-secret",
        "vision-model",
    )
    assert (verify.base_url, verify.api_key, verify.model_name) == (
        "https://verify.example/v1",
        "verify-secret",
        "verify-model",
    )
    assert (embedding.base_url, embedding.api_key, embedding.model_name) == (
        "https://embedding.example/v1",
        "embedding-secret",
        "embedding-model",
    )
    assert embedding.vector_dimension == 1024


def test_vision_name_does_not_fallback_but_verify_name_does() -> None:
    bundle = build_environment_model_bundle(
        _settings(
            llm_vision_base_url="",
            llm_vision_api_key="",
            llm_vision_model="",
            llm_verify_base_url="",
            llm_verify_api_key="",
            llm_verify_model="",
        )
    )

    vision = bundle.for_role(ModelRole.VISION)
    verify = bundle.for_role(ModelRole.VERIFY)

    assert vision.base_url == "https://primary.example/v1"
    assert vision.api_key == "primary-secret"
    assert vision.model_name == ""
    assert verify.base_url == "https://primary.example/v1"
    assert verify.api_key == "primary-secret"
    assert verify.model_name == "primary-model"


def test_endpoint_and_bundle_repr_never_include_api_keys() -> None:
    bundle = build_environment_model_bundle(_settings())

    rendered = repr(bundle)

    assert "primary-secret" not in rendered
    assert "vision-secret" not in rendered
    assert "verify-secret" not in rendered
    assert "embedding-secret" not in rendered


def test_runtime_scope_is_task_local_and_resets_after_exit() -> None:
    environment_bundle = build_environment_model_bundle(_settings())
    scoped_bundle = ModelConfigBundle(
        version_id=None,
        revision=8,
        source="database",
        models={
            role: ModelEndpointConfig(
                role=role,
                base_url=f"https://{role.value}.scoped/v1",
                api_key=f"{role.value}-scoped-secret",
                model_name=f"{role.value}-scoped-model",
                vector_dimension=1024 if role is ModelRole.EMBEDDING else None,
                source="database",
                validation_status="passed",
            )
            for role in ModelRole
        },
    )

    with model_runtime_scope(scoped_bundle):
        assert get_current_model_bundle(environment_bundle) is scoped_bundle

    assert get_current_model_bundle(environment_bundle) is environment_bundle


def test_running_execution_keeps_loaded_bundle_and_next_execution_can_use_latest() -> None:
    old_bundle = build_environment_model_bundle(_settings(llm_primary_model="old-primary"))
    latest_bundle = build_environment_model_bundle(_settings(llm_primary_model="latest-primary"))

    with model_runtime_scope(old_bundle):
        # 即使当前有效配置已经变成 latest，本次正在运行的作用域仍使用启动时的 old。
        assert get_current_model_bundle(latest_bundle) is old_bundle

    # 下一次执行重新进入作用域时即可使用最新配置。
    with model_runtime_scope(latest_bundle):
        assert get_current_model_bundle(old_bundle) is latest_bundle
