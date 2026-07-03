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

    # verify 关卡专用模型：留空则回退 llm_primary_model（行为不变）。
    # 设为非 Claude 族（如 deepseek-v4-pro-office）以消除 generator/judge 同族的 self-enhancement bias。
    llm_verify_model: str = ""

    # LLM 视觉模型（图解析用，OpenAI 兼容视觉接口；留空则传 images 时报错）
    llm_vision_model: str = ""

    # ── 图解析（Image Caption）灰度开关 ──────────────────────────────────────
    # 开：parse 时调视觉 LLM 描述图片并插回 content
    # 关：parse 行为与接入前一致（不调视觉、content 不变）
    image_caption_enabled: bool = True
    image_caption_concurrency: int = 4

    # ── 实体图谱（Entity Graph）灰度开关 ──────────────────────────────────────
    # 开：parse 时抽取实体+关系落 knowledge.entities/entity_relations
    # 关：parse 行为与接入前一致（不抽实体）
    entity_graph_enabled: bool = True
    entity_extract_concurrency: int = 4

    # ── cheat sheet 提取/注入灰度开关 ────────────────────────────────────────
    # ②a 期间默认关：未验收前不自动提取、不影响现有生成行为。
    cheat_sheet_extract_enabled: bool = False
    cheat_sheet_injection_enabled: bool = False
    # 预留给后续批量/自动提取；当前手动 API 触发按单文档同步执行。
    cheat_sheet_extract_concurrency: int = 4

    # ── 实体图谱检索开关 ──────────────────────────────────────────────────────
    # 开：生成流水线 parse 阶段挂接实体图谱关系提示
    # 关：查询返回空，不影响生成
    entity_retrieval_enabled: bool = True

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

    # ── 语义去重升级（hybrid：embedding 语义 + 词法）灰度开关 ────────────────────
    # 开：dedup_node 算各用例 embedding 传入 find_duplicates，额外抓"换措辞同义"近重复
    #   （词面抓不到的灌水大头）；候选同样过 _protected + safe_dedup 护栏。关：行为与改造前
    #   逐字节一致。建议在 safe_dedup_enabled 开时才启用（复用 rule 护栏，防误折叠最后一条）。
    # semantic_threshold：同 test_point 内语义 cosine 阈值（仿词面"同维松"）。
    # semantic_dedup_cross_tp_threshold：跨 test_point 更严阈值（仿"跨维严"，控误折叠）。
    semantic_dedup_enabled: bool = False
    semantic_dedup_threshold: float = 0.86
    semantic_dedup_cross_tp_threshold: float = 0.90

    # ── 结构化覆盖（落点⑫·线B）：权限矩阵 + 状态机有界展开 + 覆盖闸 ──────────
    structural_coverage_enabled: bool = False

    # ── verify 跨条款矛盾扫描（cherry-pick）灰度开关 ──────────────────────────
    # 开：verify 在判 verdict 之外，检查 PRD 条款间是否实质互斥（PRD 内部矛盾），
    # 标 cross_section_conflict + 两处出处，汇成 PRD 矛盾清单。关：行为与改造前一致。
    verify_cross_section_conflict_enabled: bool = True

    # ── verify 同实体门控（治概念混淆型假 conflict）灰度开关 ─────────────────────
    # 开：对 verdict=conflict 的用例做后处理——若 LLM 判 same_entity=false 或词法兜底
    # （字符集 Jaccard<0.5）判双方非同一实体（如"监测链接"≠"投放链接"），则撤销 conflict、
    # 降级 ungrounded（needs_spec）+ conflict_entity_mismatch=true，防把不同实体当同字段判矛盾。
    # 关：conflict 逐字节不动（零回归）。保守：真 conflict（同实体）不误撤。
    conflict_entity_gate_enabled: bool = True
    # 词法兜底 Jaccard 阈值：>= 阈值判同实体（不撤），< 阈值判不同实体（撤销）。
    conflict_entity_jaccard_threshold: float = 0.5
    # ── verify oracle guards（任务 07-02）灰度开关 ──────────────────────────────
    # 开：verify_cases 在 reconcile 后应用 8 个确定性 oracle guard：
    #   R1 含「需求待确认/PRD未定义」信号 → needs_spec（不删，保留风险）
    #   R2 无据的具体 toast/HTTP状态码/payload/表名 → needs_spec
    #   R3 无技术方案时，接口契约/幂等/worker/cron/轮询频率 → needs_spec（不误伤业务级）
    #   R4 cross_section_conflict=True 且 refs 非空 → 强制 to_fix，保留冲突证据
    #   R5 低信任来源(trust>=4)单独支撑高精度 oracle → needs_spec
    #   R6 外部目录/「等」无完整映射 + 唯一具体断言 → needs_spec
    # 关：verify 行为与改造前一致（零回归）。默认开（guard 只降级、不删除，风险可控）。
    oracle_guard_enabled: bool = True
    # ── verify 同构 verdict 一致化（判后聚簇，多数票统一）───────────────────────
    # 开：verify_cases 聚合后，在同 feature 内对高相似标题用例做 verdict 一致化。
    # 关：聚合结果不变，保持现状。离线评估（3185 条，阈值 0.93）已确认 14/14 真同构簇
    # 改判正确、误簇切散，默认开启；如需回退置 False。
    verdict_reconcile_enabled: bool = True
    # 默认 0.93：离线评估（batch 278c211f, 3185 条）发现 0.92 会把 IAP(35宏参数) 与
    # IAA(30宏参数) 这类仅差产品代号/数值的高相似标题误并（相似度 0.9231），导致 grounded
    # 被错误升级为 conflict。0.93 可切散该误簇且保留全部真同构簇（改判 15→13，详见 roadmap ⑤）。
    reconcile_sim: float = 0.93
    # ── verify conflict 子集复判（多次投票降抖）───────────────────────────────
    # 开：仅对首轮 verdict=conflict 的用例追加复判，按多数票覆盖首轮 verdict 后再走门控。
    # 关：单次 verify 行为不变。revote_n 表示总投票次数，默认 3。默认开启（仅 conflict 子集，
    # 成本可控）；如需回退置 False。⚠️ 5b 默认开是"未评估的主动决策"：5b 无法离线评估（需真实
    # LLM），与 5a"评估后开"标准不对齐；成本为每个含 conflict batch 额外 (revote_n-1) 次合并调用。
    # 待 Task 5 关/开对比 by_verdict.conflict 通过后视情保留或回退（详见 roadmap ⑤）。
    conflict_revote_enabled: bool = True
    revote_n: int = 3

    # ── 生成侧收敛（拆条上限 + 存在性合并 + P0 配额，roadmap ⑥）──────────────────
    # 4.1/4.2 已用 batch 278c211f 离线矩阵评估：cap=4 比 cap=3 更少裁核心维度，
    # 且仍把 3185 条收敛到约 2525 条；本轮真实跑批默认开启 merge + cap=4。
    # 4.3 P0 配额：按 risk=likelihood×impact 将非结构化低风险 P0 降为 P1；
    # 结构化覆盖点/规则锚点豁免，避免误伤权限矩阵、状态机和规则级覆盖。
    # 默认关闭：本轮真实跑批配置要求只启用 merge + cap=4，避免把 P0 配额作为额外变量混入对比。
    # 如后续单独评估 P0 泛滥治理，再显式开启 p0_quota_enabled。
    # 4.1 拆条上限：每测试点用例数超 cap 时裁剪保留多样性代表，被裁软标记 duplicate_of。
    split_cap_enabled: bool = True
    cases_per_tp_cap: int = 4
    # 4.2 存在性合并：同 (test_point_id, source_section) 的纯展示用例合并为 1 条，保留全部检查点。
    existence_merge_enabled: bool = True
    # 4.3 P0 配额：P0 占比超 quota 时按 risk 降序降 P1，结构化覆盖点豁免。
    p0_quota_enabled: bool = False
    p0_quota: float = 0.30

    # ── Hybrid 跨功能点规格检索（关键词 + 向量 + RRF）─────────────────────────────
    # 关闭时 CrossFeatureIndex 行为与改造前完全一致（纯关键词，不调 embedding，零额外开销）。
    hybrid_cross_retrieval_enabled: bool = False
    # RRF 融合常数；候选集较小（数十~一两百）时可调到 20 锐化排名差异，默认 60 为业界稳健值。
    hybrid_cross_rrf_k: int = 60

    # ── 全局章节判定去领域绑定（落点⑧）──────────────────────────────────────────
    # 关：用写死关键词 GLOBAL_HEADING_KEYWORDS 识别全局/横切章节（含领域专属词，换领域会失效）。
    # 开：用 LLM section_classifier 的语义判定（is_global），不依赖任何领域词表 → 通用。
    # 兜底：开关开但全文无 LLM 标记（分类未跑/全失败）时回退关键词。默认关，行为与改造前一致。
    global_section_llm_enabled: bool = False

    # ── 功能点切分去死板（LLM 大纲分段，切分通用化）──────────────────────────────
    # 关：用 _choose_feature_level 死规则(## = 功能点)。开：LLM 按大纲语义定功能点边界
    # （自适应粒度，嵌套 PRD 也能正确切）。LLM 失败回退死规则。默认关，行为不变。
    feature_seg_llm_enabled: bool = False

    # ── CoT 显式化 + 溯源接地（落点⑥·大改动）─────────────────────────────────
    # 关：write_cases 行为不变（用旧 provenance tagger）。开：加 CoT 分步纪律 +
    # 生成期 source_quote/source_ref 派生&校验取代「前200字」启发式 + confidence 适配。
    # 仅改 write_cases 溯源链，不动 verify 判定/输出主结构。默认关。
    grounded_provenance_enabled: bool = False

    # ── 原型多源接地（落点⑦）：MasterGo 原型 DSL 规格接入 ──────────────────────
    # 关：忽略 PRD 里的 MasterGo 链接（行为不变）。开：拉原型 DSL、抽规格并入章节内容。
    # 无链接/无 token/单链接失败均安全跳过，绝不阻断解析。
    mastergo_enabled: bool = False
    mastergo_api_token: str = ""  # env MASTERGO_API_TOKEN，勿提交

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
