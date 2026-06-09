"""应用配置管理 — 通过环境变量加载所有配置"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """全局配置，所有字段可通过同名环境变量覆盖"""

    # 应用
    app_name: str = "qa-platforms"
    app_version: str = "0.1.0"
    debug: bool = False

    # 数据库
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/qa_platforms"
    db_pool_size: int = 20
    db_max_overflow: int = 10

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Celery
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # MinIO
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "qa-documents"
    minio_secure: bool = False

    # LLM 网关（OpenAI 兼容协议；指向自建网关即可，留空走 OpenAI 官方）
    llm_base_url: str = ""  # 网关地址，如 https://your-gateway/v1
    llm_api_key: str = ""  # 网关 key（留空回退 openai_api_key）
    llm_primary_model: str = ""  # 必须在 .env 配 LLM_PRIMARY_MODEL，漏配则启动时报错
    # 主模型失败重试次数。调小以免单个 504（每次 ~260s）反复重试长时间拖住串行流水线，
    # 让失败快速触发"功能点失败隔离"、保住其余功能点的产出。
    llm_max_retries: int = 2
    # 网关 504 的根因是「单次输出过长」，已通过 test-points 按功能点数、write-cases 按测试点数
    # 切批把每次输出压短解决。输出短后并发 2 的两个请求都很快返回、不再压垮网关，故用 2 提速。
    # 网关扩容后可继续调高。
    llm_concurrency: int = 2  # test-points / write-cases 阶段并发调用数

    # Embedding（默认复用 LLM 网关，可单独覆盖）
    openai_api_key: str = ""  # 兼容旧字段，作为各处 key 的最终回退
    embedding_base_url: str = ""  # 留空回退 llm_base_url
    embedding_api_key: str = ""  # 留空回退 llm_api_key / openai_api_key
    openai_embedding_model: str = "text-embedding-3-small"

    @property
    def resolved_llm_base_url(self) -> str | None:
        return self.llm_base_url or None

    @property
    def resolved_llm_api_key(self) -> str:
        return self.llm_api_key or self.openai_api_key

    @property
    def resolved_embedding_base_url(self) -> str | None:
        return self.embedding_base_url or self.llm_base_url or None

    @property
    def resolved_embedding_api_key(self) -> str:
        return self.embedding_api_key or self.llm_api_key or self.openai_api_key

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
