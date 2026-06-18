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
    # 单次 LLM 请求的硬超时（秒）。根治"无超时导致一次卡住的请求把整阶段挂死 600s+"：
    # 超时即抛错 → 走 tenacity 重试 → 仍失败则子批失败隔离，不再无限白等。
    # 取 240：略低于自建网关 ~260s 的 504 阈值，让客户端先于网关超时、快速重试。
    llm_timeout: float = 240.0
    # 是否启用 OpenAI 兼容的 response_format=json_object（JSON mode）。
    # 默认 False：当前自建网关对该参数为「哑支持」——不报错，但会把 finish_reason 标成
    # tool_calls 却不返回任何 tool_calls、content 直接为空 {}，导致结果不可恢复（实测见
    # .qa_probe/rule_extract/_diag_result.json）。故默认关闭，JSON 稳定性靠「短批切分 +
    # 容错解析」保障。保留此开关：将来换成真正支持 json_object 的网关时置 True 即可启用。
    llm_json_mode: bool = False

    # LLM 视觉模型（图解析用，OpenAI 兼容视觉接口；留空则传 images 时报错）
    llm_vision_model: str = ""

    # ── 图解析（Image Caption）灰度开关 ──────────────────────────────────────
    # 开：parse 时调视觉 LLM 描述图片并插回 content
    # 关：parse 行为与接入前一致（不调视觉、content 不变）
    image_caption_enabled: bool = False
    image_caption_concurrency: int = 4

    # ── 实体图谱（Entity Graph）灰度开关 ──────────────────────────────────────
    # 开：parse 时抽取实体+关系落 knowledge.entities/entity_relations
    # 关：parse 行为与接入前一致（不抽实体）
    entity_graph_enabled: bool = False
    entity_extract_concurrency: int = 4

    # ── test_points 完整性兜底 ──────────────────────────────────────────────────
    # 开：批失败重试 + 单 feature 降级 + 缺额校验（修 9 feature 静默丢失）
    # 关：退回旧行为（失败批静默丢弃）——纯止血，默认开。
    test_points_completeness_guard: bool = True

    # ── 规则锚定覆盖（Rule-Anchored Coverage）灰度开关 ──────────────────────────
    # 解耦设计，可独立回滚（详见 docs/plans/2026-06-15-rule-anchored-coverage.md）：
    #   rule_extract_enabled         — 仅产规则台账（rule_extract 阶段），不改生成。无依赖。
    #   rule_driven_testpoints_enabled — test_points 规则驱动+维度增强。依赖 rule_extract_enabled。
    #   rule_coverage_gate_enabled   — review 规则级覆盖闸 + 定向 backfill。依赖 rule_driven_testpoints。
    #   safe_dedup_enabled           — 规则锚定安全去重。依赖 rule_id 链路（rule_driven_testpoints）。
    # 启用顺序铁律：开 gate/safe_dedup 前必须先开 rule_driven_testpoints，否则空转/误判。
    rule_extract_enabled: bool = False
    rule_driven_testpoints_enabled: bool = False
    rule_coverage_gate_enabled: bool = False
    safe_dedup_enabled: bool = False
    # rule_extract 阶段抽规则的并发（输出短，可略高于生成阶段的 llm_concurrency）
    rule_extract_concurrency: int = 4

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
