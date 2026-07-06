"""Oracle Guards（任务 07-02）— verify 回挂后的确定性后处理闸。

对 LLM 给出的 verdict/bucket 做确定性复核，复用现有 verdict/bucket/source_ref/
trust_order(trust_level)/cross_section_conflict 字段，不另起模型。

9 个 guard（对应 PRD R1-R8 + 断言质量闸）：
- R1 澄清信号分流：标题/步骤/预期含「需求待确认/待确认/PRD未定义/无确定断言」→ 不进 main
- R2 Fake Oracle：无据的具体 toast/HTTP 状态码/payload/表名 → 不进 main
- R3 No-Tech-Spec：无技术方案时，接口契约/幂等/worker/cron/轮询频率 → 不进 main（不误伤业务级）
- R4 cross_section_conflict=True 且 refs 非空 → 强制 to_fix，保留冲突证据
- R5 低信任证据（原型/AI caption, trust_level>=4）单独支撑精确文案/布局 → 不进 main
- R6 外部目录/"等"不完整 + 唯一具体映射断言 → 不进 main
- R7 字数/数量边界：确定性算法（见 length_check.char_count_halfwidth_units）与硬事实约束
- R8 不删数据：guard 只改 bucket，不从结果集移除任何用例
- R9 纯模糊预期：只有“正常显示/信息正确/符合预期”等不可执行断言 → 不进 main
- R4 同层/同实体补充：状态展示文案与业务状态机命名差异不能作为硬 conflict 执行

设计原则：
- 只把 main 降级到 needs_spec/to_fix，绝不删除用例（R8）。
- 风险文本/证据全部保留（unsupported_assertions / conflicting_refs）。
- verdict 一般不改（尊重 LLM 判断），仅 R4 用 bucket 强制分流（冲突是 PRD 的问题，
  需产品裁决，不能留 main 执行）。R1-R3/R5/R6 若 LLM 已判 grounded 但 guard 判定
  不应进 main，则将 verdict 降为 ungrounded（无据）或 undefined（未定义/未确认），
  bucket 降为 needs_spec，并在 rationale 追加 guard 原因。R7 遇到确定性 PRD 硬规则冲突时可
  降为 conflict/to_fix。
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlsplit

from src.testcase_generator.schemas.test_case import CaseVerification, ReviewIssueType
from src.testcase_generator.services.assertion_quality import is_pure_vague_assertion_case
from src.testcase_generator.services.prd_facts import (
    unsupported_closed_enum_assertion,
    unsupported_unique_fact_assertion,
    unsupported_upper_bound_assertion,
)

# ── R1 澄清信号 ──────────────────────────────────────────────────────────────
# 标题/步骤/预期/rationale/source_quote 中出现这些信号 → 该用例针对"待确认/未定义"行为
# 做了具体断言，不得进 main。注意匹配需覆盖带书名号/方括号的变体。
_CLARIFICATION_SIGNALS: tuple[str, ...] = (
    "需求待确认",
    "待确认",
    "prd未定义",
    "无确定断言",
    "无确定预期",
    "待补规格",
)


def _has_clarification_signal(*texts: str) -> bool:
    blob = " ".join(t or "" for t in texts).lower()
    return any(sig in blob for sig in _CLARIFICATION_SIGNALS)


# ── R2/R3 高精度 oracle 与技术派生断言的词法特征 ────────────────────────────
# R2：高精度 oracle（需 PRD/tech 直接支撑，否则 fake）
# HTTP 状态码必须带 HTTP/状态码/返回码/响应码/接口返回码 上下文——裸三位数字（TP-471、
# 容量 500/521/522）是业务取值，不是状态码 oracle（任务 07-02 第三轮收窄）。
_HTTP_STATUS_RE = re.compile(
    r"HTTP\s*\d{3}|状态码\s*\d{3}|返回码\s*\d{3}|响应码\s*\d{3}|接口返回码\s*\d{3}|"
    r"HTTP\s*状态码\s*\d{3}",
    re.I,
)
# 精确 toast/文案断言：带引号的具体文案（≥3 字符），排除泛指。
# 单独匹配不判 fake——必须结合 _FAKE_COPY_CONTEXT（toast/提示文案/错误提示/弹窗文案/
# placeholder/显示文案/报错信息）上下文，避免把业务枚举/按钮名/字段名/测试数据当 fake 文案。
_QUOTED_COPY_RE = re.compile(r"[「『\"']([^」』\"']{3,})[」』\"']")
# PRD 常用「已选 N」「已更新 N 个账户」表示运行时数量文案。这里仅支持独立 N 占位，
# 避免误把英文 token 里的 N 当变量；其余文字仍需逐字一致。
_COPY_PARAM_PLACEHOLDER_RE = re.compile(r"(?<![A-Za-z0-9_])N(?![A-Za-z0-9_])")
_MARKDOWN_BOLD_COPY_TEMPLATE_RE = re.compile(r"\*\*([^*\n]{0,80}(?<![A-Za-z0-9_])N(?![A-Za-z0-9_])[^*\n]{0,80})\*\*")
# 文案类 fake oracle 的上下文关键词：出现这些词时，引号内容才视为"精确文案断言"。
# 不含「按钮」（按钮名是 UI 标签非文案断言）、「返回」（接口返回业务描述）。
_FAKE_COPY_CONTEXT: tuple[str, ...] = (
    "toast",
    "提示文案",
    "提示信息",
    "错误提示",
    "报错信息",
    "错误信息",
    "弹窗文案",
    "弹窗提示",
    "placeholder",
    "占位文案",
    "显示文案",
    "文案为",
    "提示为",
)
# 业务取值/测试数据排除：引号内是纯数字、纯字母数字（test/xyz/1234567890）、
# 或业务枚举标识（含 ROI/IAA/IAP/CBO 等大写缩写），不视为 fake 文案 oracle。
_BUSINESS_VALUE_RE = re.compile(r"^[A-Z0-9_]+$|^\d+$|^[a-z0-9]+$")
# 计算式排除：含 × * = 或「数×数」形态的引号内容是业务计算，非文案。
_CALC_RE = re.compile(r"[×*=]|\d+\s*[×*]\s*\d+")
# 具体表名/字段落库断言
_DB_TABLE_RE = re.compile(r"(?:落库|写入|存入|表|table)\s*[:：]?\s*[`'\"]?([a-z_][a-z0-9_]{2,})[`'\"]?", re.I)
# 具体 payload/响应结构（Finding 1：放宽为"请求体/响应体/payload + 包含/字段/:"均命中）
_PAYLOAD_RE = re.compile(
    r"(?:payload|请求体|响应体|response|body)\s*[:：]|"
    r"(?:请求体|响应体|payload)\s*(?:包含|字段|参数)",
    re.I,
)

# R3：技术派生断言（无技术方案时禁止进 main）
# 分两类：强信号（硬技术派生，命中即判技术断言，绝不放行业务级）与泛词（可能出现在业务描述里，
# 如"失败后可重试提交"，需 _is_business_level_rule_only 结合上下文判断）。
# _detect_tech_derived_assertion 用【最长匹配】返回命中——"指数退避"(4字)优先于"重试"(2字)，
# 避免"指数退避重试"被泛词"重试"抢占后又被业务级放行（audit P1-3 残留漏洞）。
_TECH_STRONG_SIGNALS: tuple[str, ...] = (
    "幂等键",
    "幂等",
    "指数退避",
    "熔断",
    "限流",
    "worker",
    "cron",
    "定时任务",
    "轮询",
    "polling",
    "消息队列",
    "mq",
    "kafka",
    "rabbitmq",
    "redis 锁",
    "分布式锁",
    "事务回滚",
    "乐观锁",
    "悲观锁",
    "binlog",
    "canal",
    "双写",
)
_TECH_GENERIC_SIGNALS: tuple[str, ...] = ("重试",)
# 幂等业务规则证据词：evidence 含这些表述时，"幂等"作为业务级断言可放行（不判技术派生）。
# 裸"幂等"默认是技术实现断言，不应因文本含提交/失败/保存被业务级放行（Finding 2）。
_IDEMPOTENCE_BUSINESS_RULE_RE = re.compile(
    r"重复提交[^。]*?(?:不产生|不创建|不会|不重复)|不会创建重复|不产生重复(?:记录|数据|订单)",
)
# 接口契约信号（R3）：API path / method / 响应结构契约 / 幂等键。
# 注意：不含裸「接口返回」（业务描述常用，如"接口返回成功"），避免误判业务级为技术派生。
_API_CONTRACT_RE = re.compile(
    r"/api/|/v\d+/|GET\s+|POST\s+|PUT\s+|DELETE\s+|PATCH\s+|"
    r"接口契约|响应结构|response\s*schema|"
    r"X-Idempotency|idempotency",
    re.I,
)
# API method + path 完整片段（Finding 1）：提取 "POST /api/accounts/bulk-assign" 整体，
# 而非泛片段 "POST " / "/api/"——用于 R2 精确证据比对，避免 case 断言 bulk-assign 但 evidence
# 只有 /api/accounts/list 时因 "POST " 子串匹配误判支撑。
_API_METHOD_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_])(GET|POST|PUT|DELETE|PATCH)\s+(\/[A-Za-z0-9_\-\/{}:]+)",
    re.I,
)
# payload/请求体字段提取（Finding 1 + 二审 F1-payload + 二审 P1 多 atom + 四审 P1 上下文区分）：
# 支持 "请求体包含字段 ids 和 owner" / "请求体包含 ids 和 owner" /
# "payload 包含 ids, owner" / "响应体包含 code 和 data" 等句式，提取字段名列表。
# 字段名只允许标识符 [a-zA-Z_][a-zA-Z0-9_]*，分隔符仅 [,，和]（+ 可选空格）——
# 不含裸 \s，避免吞掉后续 "POST /path" 的 method token（二审 P1：字段不能解析成 "ids 和 owner POST"）。
# evidence 必须含【全部】字段名才判支撑。
# 四审 P1：捕获上下文关键词（请求体/响应体/payload/字段/参数），atom 带 ctx（request/response/generic），
# evidence 按同 ctx 精确字段集合匹配——请求体 code 不能支撑响应体 code。
_FIELD_LIST_RE = r"[a-zA-Z_][a-zA-Z0-9_]*(?:\s*[,，和]\s*[a-zA-Z_][a-zA-Z0-9_]*)*"
# ctx 后允许 "包含/字段/参数/:" 连接词（四审 P1：支持"请求体包含 ids""响应体包含 code"等句式）
_PAYLOAD_FIELD_RE = re.compile(
    r"(?P<ctx>请求体|响应体|payload|response|body|字段|参数)"
    r"\s*(?:包含|字段|参数)?\s*[:：]?\s*(?P<fields>" + _FIELD_LIST_RE + r")",
    re.I,
)


def _payload_context_of(keyword: str) -> str:
    """把 payload 上下文关键词归为 request / response / generic。"""
    low = (keyword or "").lower()
    if "响应" in keyword or low in ("response",):
        return "response"
    if "请求" in keyword or low in ("payload", "body") or "body" in low:
        return "request"
    # "字段/参数" 无明确请求/响应上下文 → generic
    return "generic"


# worker/cron/轮询频率具体数值断言
_SCHEDULE_RE = re.compile(r"每\s*\d+\s*(秒|分钟|小时|s|second|min)|\d+\s*秒.*轮询|轮询.*\d+\s*秒", re.I)
_SCHEDULED_TASK_EVIDENCE_RE = re.compile(
    r"(?:定时任务|定时|定期|调度|每天|每日|凌晨)[^。；;]*(?:遍历|拉取|同步|执行|触发)|"
    r"(?:遍历|拉取|同步|执行|触发)[^。；;]*(?:定时任务|定时|定期|调度|每天|每日|凌晨)"
)


def _is_business_level_rule(text: str) -> bool:
    """判断是否为 PRD 明确的业务级规则（权限/安全/状态/边界/异常），不应被 R3 误杀。

    业务级关键词出现且不含技术派生信号时，视为合法业务规则。
    """
    business_signals = (
        "权限",
        "无权",
        "禁止",
        "拒绝",
        "管理员",
        "角色",
        "可见",
        "安全",
        "敏感",
        "越权",
        "鉴权",
        "状态",
        "草稿",
        "待审核",
        "已发布",
        "驳回",
        "提交",
        "保存",
        "不超过",
        "最多",
        "最少",
        "至少",
        "上限",
        "下限",
        "字",
        "必填",
        "校验",
        "阻断",
        "提示错误",
        "失败",
    )
    return any(sig in text for sig in business_signals)


# ── R5 低信任来源判定 ────────────────────────────────────────────────────────
# trust_level >= 4 视为低信任（原型=5, AI caption 一般挂在低信任 source）。
# 默认无 source_trust 映射时不降权（保守，不误伤有 PRD 支撑的用例）。
_LOW_TRUST_THRESHOLD = 4


def _is_high_precision_oracle(text: str) -> bool:
    """R5/R2 共用：判定是否为"高精度 oracle"（精确文案/布局/状态码/payload）。"""
    return bool(
        _HTTP_STATUS_RE.search(text)
        or _QUOTED_COPY_RE.search(text)
        or _DB_TABLE_RE.search(text)
        or _PAYLOAD_RE.search(text)
        or _API_CONTRACT_RE.search(text)
    )


# R7：确定性自检失败（字数/计数/参数数量）不能作为可执行主集。
_HIGH_RISK_CONFIDENCE_RE = re.compile(
    r"字数声明与输入不符|自检不一致|计数.*不一致|数量.*不一致|参数.*不一致|宏参数.*不一致"
)
_URL_RE = re.compile(r"https?://[^\s，。；;）)]+")
_QUERY_PARAM_COUNT_RE = re.compile(
    r"(?P<count>\d+)\s*个\s*(?:宏参数|query\s*参数|查询参数|参数名|参数)",
    re.I,
)
_TEMPLATE_ASSERTION_CONTEXT_RE = re.compile(r"(?:项目名称|广告名称|任务名称|名称|命名)?模板")
_TEMPLATE_CHAR_LIMIT_RE = re.compile(
    r"(?:长度上限每条模板|每条模板(?:长度)?上限|单条模板(?:长度)?上限|模板(?:长度)?上限)"
    r"\s*(?P<limit>\d+)\s*字符"
)
_HALFWIDTH_CHAR_COUNT_RE = re.compile(r"(?P<count>\d+)\s*个?\s*半角(?:字母|字符|数字|符号|英文)")
_HALFWIDTH_ACCEPT_RE = re.compile(
    r"(?:未|不)(?:超出|超过)上限|未超限|不超限|"
    r"可保存|保存成功|校验通过|通过校验|未拦截|不拦截|可通过"
)

# R4 同层/同实体补充：任务列表 UI 执行状态展示文案 vs 业务状态机内部/业务状态名。
# 只覆盖已知双口径形态：case 断言「列表/执行状态列/mock/partial」展示「部分失败」，
# 证据/PRD 侧只有业务状态机名「提交完成-有失败」。这不是可执行真 conflict；
# 但如果缺少同层 UI 证据，也不能直接升回 main，应进入 needs_spec 待补证据。
_TASK_STATUS_PARTIAL_STATE_RE = re.compile(r"提交完成-有失败")
_TASK_STATUS_DISPLAY_PARTIAL_RE = re.compile(
    r"(?:列表|执行状态列|mock|partial)[^。；;]*部分失败|"
    r"部分失败[^。；;]*(?:列表|执行状态列|mock|partial)",
    re.I,
)
_TASK_STATE_NAME_PARTIAL_RE = re.compile(
    r"(?:任务状态机|状态机|业务状态|任务状态)[^。；;]*部分失败|"
    r"部分失败[^。；;]*(?:任务状态机|状态机|业务状态|任务状态)",
    re.I,
)

# R4 同层/同实体补充：投放链接（批创表单内可选链接列表）与监测链接（IAP/IAA
# 预置宏参数链接、提交时自动绑定）是两个不同实体。不能用监测链接“投手无需选择”
# 反驳投放链接列表空态，也不能用投放链接单选控件反驳监测链接自动绑定规则。
_DELIVERY_LINK_ENTITY_RE = re.compile(r"投放链接|当前投放方式下没有可用链接|投放链接管理")
_MONITORING_LINK_ENTITY_RE = re.compile(
    r"监测链接|预置监测链接|宏参数|IAP|IAA|自动绑定|投手无需(?:选|选择|填)|无需关心宏参数",
    re.I,
)

# R4 同层补充：定向包地理位置 UI 选择上限（第 1001 个区县起阻止勾选）
# 与接口层地区字符串收录上限（单次 200 条、超出截断）是不同抽象层。不能用接口载荷
# 约束直接反驳 UI 交互约束；但同为接口层的 1000 vs 200 仍应保留 hard conflict。
_GEO_UI_SELECTION_LIMIT_RE = re.compile(
    r"(?=.*(?:地理位置|地区|区县|已选地区))"
    r"(?=.*(?:1000|1001))"
    r"(?=.*(?:勾选|红框|红色提示|已选清单|冻结|阻止|选择上限|超出时))",
    re.S,
)
_GEO_INTERFACE_PAYLOAD_LIMIT_RE = re.compile(
    r"(?:接口层|提交载荷|载荷|payload|下发|收录)[^。；;]{0,80}(?:200\s*条|地区字符串|截断)|"
    r"(?:200\s*条地区字符串)[^。；;]{0,60}(?:接口层|收录|截断)"
)
_NUM_UNIT_RE = re.compile(
    r"(?P<count>\d+)\s*(?:个|条)?\s*"
    r"(?P<unit>创意组|组|素材|视频|区县|地区字符串|地区|账户|标题|广告任务|宏参数|query\s*参数|查询参数|字|字符)",
    re.I,
)


# ── 主入口 ───────────────────────────────────────────────────────────────────


def apply_oracle_guards(
    results: dict[str, CaseVerification],
    cases: list,
    *,
    tech_source_refs: set[str] | None = None,
    source_trust: dict[str, int] | None = None,
    conflict_entity_gate_enabled: bool = True,
) -> dict[str, CaseVerification]:
    """对 verify 结论应用 8 个 oracle guard，返回更新后的 results。

    参数：
    - results: {case_id: CaseVerification}，verify_cases 的输出。
    - cases: list[VerifyCase]，与 results 同序的用例输入（取 title/steps/source_quote/source_ref）。
    - tech_source_refs：技术方案源(tech_doc)的 source_ref 集合。R3 用它精确判断技术断言
      是否被技术方案支撑——而非全局一刀切（避免无关模块的 worker/cron 断言被放行）。
    - source_trust: {source_ref: trust_level}，用于 R5 低信任降权。缺省时不降权。

    不变量：
    - 不删除任何 case_id（R8）。
    - 默认只把 ``bucket='main'`` 降级；非 main 一般不动，R4 同层/同实体补充
      可把已误判的 ``to_fix/conflict`` 降为 ``needs_spec/undefined``。
    - 冲突证据（conflicting_refs）绝不清理（R4）。
    """
    source_trust = source_trust or {}
    tech_source_refs = tech_source_refs or set()
    # 预处理：case_id → (用例断言文本, source_quote, source_refs 列表)
    # 断言文本 = 标题 + 步骤action/expected_result + expected_results（不含 source_quote，
    # 因为 R2 要判断"断言的具体 oracle 是否被 source_quote 支撑"，二者须分开）。
    # source_refs 收集【所有】 step 的 source_ref（R5 多 step 漏判修复：任一 step 来自低信任
    # 来源即应触发降权，不能只查首个 step）。
    case_assertion: dict[str, str] = {}
    case_quote: dict[str, str] = {}
    case_source_refs: dict[str, list[str]] = {}
    case_provenance: dict[str, str] = {}
    case_confidence: dict[str, str] = {}
    case_expected_assertions: dict[str, list[str]] = {}
    for c in cases:
        parts = [c.title or ""]
        quotes: list[str] = []
        refs: list[str] = []
        expected_assertions: list[str] = []
        for s in getattr(c, "steps", []) or []:
            parts.append(str(s.get("action", "")))
            step_expected = str(s.get("expected_result", ""))
            parts.append(step_expected)
            if step_expected:
                expected_assertions.append(step_expected)
            sq = s.get("source_quote")
            if sq:
                quotes.append(str(sq))
            ref = s.get("source_ref")
            if ref:
                refs.append(_normalize_ref(str(ref)))
        for er in getattr(c, "expected_results", []) or []:
            expected_result = str(er)
            parts.append(expected_result)
            if expected_result:
                expected_assertions.append(expected_result)
        case_assertion[c.case_id] = " ".join(parts)
        case_quote[c.case_id] = " ".join(quotes)
        case_source_refs[c.case_id] = refs
        case_expected_assertions[c.case_id] = expected_assertions
        # provenance_excerpt 是用例溯源摘录（write_cases 期的 verbatim_excerpt），与
        # source_quote/prd_evidence 同为证据来源，合入 evidence 池（Finding 3）。
        pe = getattr(c, "provenance_excerpt", None)
        case_provenance[c.case_id] = str(pe) if pe else ""
        cn = getattr(c, "confidence_note", None)
        case_confidence[c.case_id] = str(cn) if cn else ""

    # source_trust 的 key 也归一化（与 step.source_ref 同口径匹配，防 LLM 改写空格/大小写致 R5 失效）
    norm_source_trust = {_normalize_ref(k): v for k, v in source_trust.items()}
    norm_tech_refs = {_normalize_ref(r) for r in tech_source_refs}

    guarded: dict[str, CaseVerification] = {}
    for case_id, ver in results.items():
        guarded[case_id] = _apply_single(
            ver,
            assertion=case_assertion.get(case_id, ""),
            source_quote=case_quote.get(case_id, ""),
            provenance_excerpt=case_provenance.get(case_id, ""),
            confidence_note=case_confidence.get(case_id, ""),
            expected_assertions=case_expected_assertions.get(case_id, []),
            src_refs=case_source_refs.get(case_id, []),
            tech_source_refs=norm_tech_refs,
            source_trust=norm_source_trust,
            conflict_entity_gate_enabled=conflict_entity_gate_enabled,
        )
    return guarded


def _normalize_ref(ref: str) -> str:
    """归一化 source_ref 用于匹配：strip + 折叠连续空白 + 小写。

    step.source_ref 是 LLM 生成字段，可能多/少空格或大小写差异；source_trust 的 key
    来自 parsed_context 直取。归一化后匹配，防 R5 静默失效。
    """
    return " ".join((ref or "").split()).lower()


def _route_to_needs_spec(
    ver: CaseVerification,
    *,
    new_verdict: str,
    reason: str,
    unsupported: list[str] | None = None,
    review_issue_type: ReviewIssueType | None = None,
) -> CaseVerification:
    """把当前结论分流到 needs_spec，verdict 降为 new_verdict，rationale 追加 guard 原因。

    保留 unsupported_assertions（追加），不清任何冲突证据。
    """
    updates: dict = {
        "verdict": new_verdict,
        "bucket": "needs_spec",
        "rationale": f"{ver.rationale}（oracle guard：{reason}）",
    }
    if unsupported:
        existing = list(ver.unsupported_assertions or [])
        for u in unsupported:
            if u not in existing:
                existing.append(u)
        updates["unsupported_assertions"] = existing
    if review_issue_type:
        updates["review_issue_type"] = review_issue_type
    return ver.model_copy(update=updates)


def _route_to_to_fix_conflict(
    ver: CaseVerification,
    *,
    reason: str,
    unsupported: list[str],
    review_issue_type: ReviewIssueType = "case_wrong",
) -> CaseVerification:
    """把确定性 PRD 硬规则冲突分流到 to_fix/conflict，并保留冲突断言。"""
    existing = list(ver.unsupported_assertions or [])
    for u in unsupported:
        if u not in existing:
            existing.append(u)
    return ver.model_copy(
        update={
            "verdict": "conflict",
            "bucket": "to_fix",
            "rationale": f"{ver.rationale}（oracle guard：{reason}）",
            "unsupported_assertions": existing,
            "review_issue_type": review_issue_type,
        }
    )


def _infer_review_issue_type(ver: CaseVerification) -> ReviewIssueType | None:
    """基于最终核验形态补齐审查诊断类型。"""
    if ver.cross_section_conflict and ver.conflicting_refs:
        return "prd_conflict"
    if ver.conflict_entity_mismatch:
        return "verify_uncertain"
    if ver.verdict == "conflict" or ver.bucket == "to_fix":
        return "case_wrong"
    return None


def _apply_single(
    ver: CaseVerification,
    *,
    assertion: str,
    source_quote: str,
    provenance_excerpt: str,
    confidence_note: str,
    expected_assertions: list[str],
    src_refs: list[str],
    tech_source_refs: set[str],
    source_trust: dict[str, int],
    conflict_entity_gate_enabled: bool,
) -> CaseVerification:
    """对单条用例应用全部 guard。

    - ``assertion``：用例自身断言文本（标题/步骤/预期），用于检测高精度 oracle / 技术派生信号。
    - ``source_quote``：用例生成期挂的 PRD 引文。
    - ``provenance_excerpt``：用例溯源摘录（write_cases 期的 verbatim_excerpt）。
    - ``ver.prd_evidence``：verify 阶段 LLM 找到的 PRD 证据。
      以上三者合并为"已有证据"池（_merge_evidence）——R2/R3/R6 据此判断断言是否被支撑。
      R2 必须同时看三者——否则任一证据源缺失时会被误降级，让后处理覆盖事实核验结果（Finding 3）。
    - ``src_refs``：用例所有 step 的 source_ref 列表（已归一化）。R5 取其中最低信任者判定，
      R3 用其判断是否命中技术方案源——多 step 场景任一 step 来自低信任/技术源都应生效。

    guard 顺序：R4（冲突最优先）→ R1 → R9 → R7 → R2 → R3 → R6 → R5。
    """
    # R4：cross_section_conflict=True 且 refs 非空 → 强制 to_fix，保留证据。
    # 这是业务规则变更：冲突用例不能留 main 执行，必须分流待产品裁决。
    if ver.cross_section_conflict and ver.conflicting_refs:
        if ver.bucket != "to_fix":
            return ver.model_copy(
                update={
                    "bucket": "to_fix",
                    "rationale": f"{ver.rationale}（oracle guard R4：PRD 跨条款冲突，分流待产品裁决）",
                    "review_issue_type": "prd_conflict",
                }
            )
        if ver.review_issue_type != "prd_conflict":
            return ver.model_copy(update={"review_issue_type": "prd_conflict"})
        return ver  # 已在 to_fix，不动

    # R4 修正：cross_section_conflict=True 但无 refs → 防御性假信号，修正为 False
    if ver.cross_section_conflict and not ver.conflicting_refs:
        ver = ver.model_copy(update={"cross_section_conflict": False})

    # 合并证据池：生成期 source_quote + 溯源摘录 provenance_excerpt + verify 期 prd_evidence
    # （Finding 3：三者均为证据来源，缺一会误降级）。
    # R2/R3/R6 判断"断言是否被证据支撑"时统一用此池；R4 同层补充也复用它判断 PRD 侧状态名。
    evidence = _merge_evidence(source_quote, provenance_excerpt, ver.prd_evidence)

    layer_mismatch = _detect_task_status_display_layer_mismatch(assertion, evidence, ver)
    if layer_mismatch:
        return _route_to_needs_spec(
            ver,
            new_verdict="undefined",
            reason=f"R4 {layer_mismatch}",
            unsupported=[layer_mismatch],
            review_issue_type="verify_uncertain",
        ).model_copy(update={"conflict_entity_mismatch": True})

    unanchored_conflict = _detect_unanchored_numeric_conflict_assertion(assertion, ver)
    if unanchored_conflict:
        return _route_to_needs_spec(
            ver,
            new_verdict="undefined",
            reason=f"R4 {unanchored_conflict}",
            unsupported=[unanchored_conflict],
            review_issue_type="verify_uncertain",
        ).model_copy(update={"conflict_entity_mismatch": True})

    geo_layer_mismatch = _detect_geo_selection_interface_layer_mismatch(assertion, source_quote, ver)
    if geo_layer_mismatch:
        return _route_to_needs_spec(
            ver,
            new_verdict="undefined",
            reason=f"R4 {geo_layer_mismatch}",
            unsupported=[geo_layer_mismatch],
            review_issue_type="verify_uncertain",
        ).model_copy(update={"conflict_entity_mismatch": True})

    link_entity_mismatch = (
        _detect_link_entity_mismatch(assertion, source_quote, ver) if conflict_entity_gate_enabled else None
    )
    if link_entity_mismatch:
        return _route_to_needs_spec(
            ver,
            new_verdict="undefined",
            reason=f"R4 {link_entity_mismatch}",
            unsupported=[link_entity_mismatch],
            review_issue_type="verify_uncertain",
        ).model_copy(update={"conflict_entity_mismatch": True})

    # 非 main 的用例不再重复降级（保留 LLM/既有判断，避免 rationale 累积污染）
    if ver.bucket != "main":
        inferred_issue_type = _infer_review_issue_type(ver)
        if inferred_issue_type and ver.review_issue_type != inferred_issue_type:
            return ver.model_copy(update={"review_issue_type": inferred_issue_type})
        return ver

    # R1：澄清信号（断言或 rationale 或证据含）→ needs_spec（undefined，待确认）
    if _has_clarification_signal(assertion, ver.rationale or "", evidence):
        return _route_to_needs_spec(
            ver,
            new_verdict="undefined",
            reason="R1 含需求待确认/未定义信号",
            review_issue_type="verify_uncertain",
        )

    # R9：纯模糊预期（如“页面正常显示/信息正确/符合预期”）不可执行，不应进入 stable main。
    if is_pure_vague_assertion_case(expected_assertions, ()):
        return _route_to_needs_spec(
            ver,
            new_verdict="undefined",
            reason="R9 预期结果只有纯模糊断言，缺少可观察状态/数值/字段/副作用",
            unsupported=expected_assertions,
            review_issue_type="case_wrong",
        )

    # R7：确定性自检失败（字数/计数/参数数量不一致）→ needs_spec。
    # 这类 case 不是低置信来源，而是输入样例与自身 oracle 不一致；继续放 main 会污染执行集。
    if confidence_note and _HIGH_RISK_CONFIDENCE_RE.search(confidence_note):
        return _route_to_needs_spec(
            ver,
            new_verdict="undefined",
            reason=f"R7 确定性自检失败：{confidence_note}",
            unsupported=[confidence_note],
            review_issue_type="case_wrong",
        )

    query_count_conflict = _detect_query_param_count_conflict(assertion, evidence)
    if query_count_conflict:
        return _route_to_needs_spec(
            ver,
            new_verdict="undefined",
            reason=f"R7 确定性参数数量不一致：{query_count_conflict}",
            unsupported=[query_count_conflict],
            review_issue_type="case_wrong",
        )

    template_limit_conflict = _detect_template_character_limit_conflict(assertion, evidence)
    if template_limit_conflict:
        return _route_to_to_fix_conflict(
            ver,
            reason=f"R7 确定性模板字符上限冲突：{template_limit_conflict}",
            unsupported=[template_limit_conflict],
        )

    upper_bound_conflict = unsupported_upper_bound_assertion(assertion, evidence)
    if upper_bound_conflict:
        return _route_to_to_fix_conflict(
            ver,
            reason=f"R7 确定性数量上限冲突：{upper_bound_conflict}",
            unsupported=[upper_bound_conflict],
        )

    closed_enum_conflict = unsupported_closed_enum_assertion(assertion, evidence)
    if closed_enum_conflict:
        return _route_to_to_fix_conflict(
            ver,
            reason=f"R7 确定性枚举事实冲突：{closed_enum_conflict}",
            unsupported=[closed_enum_conflict],
        )

    # R2：fake oracle（高精度具体数值/文案/表名 oracle 无据）→ needs_spec（ungrounded）。
    # 先于 R3：状态码/表名/文案是 fake oracle（R2），不是技术派生（R3）。
    # "有据"= evidence（source_quote ∪ provenance_excerpt ∪ prd_evidence）已含该具体 oracle 内容。
    # 二审 P1 多 atom：收集【所有】高精度 oracle atom，任一无支撑即分流；unsupported 记录全部
    # 未支撑 atom（避免只查首个 atom 导致"payload 有支撑但 endpoint 错"漏判）。
    atoms = _detect_fake_oracles(assertion)
    unsupported_atoms = [a for a in atoms if not _evidence_supports(evidence, a)]
    if unsupported_atoms:
        shown = "、".join(unsupported_atoms[:3])
        return _route_to_needs_spec(
            ver,
            new_verdict="ungrounded",
            reason=f"R2 无 PRD 支撑的具体 oracle「{shown}」",
            unsupported=unsupported_atoms,
            review_issue_type="case_wrong",
        )

    # R3：技术派生断言（API契约/幂等/worker/cron）需被"技术方案"支撑才可进 main。
    # 不再用全局 has_tech_spec 一刀切放行——否则无关模块的技术断言会因 batch 含 tech_doc 而漏进 main。
    # 放行条件（满足其一）：技术断言被当前 case 的 evidence 直接支撑（证据里就写了该技术细节），
    # 或当前 case 任一 step 的 source_ref 命中 tech_source_refs（证据来自技术方案文档）。
    # 幂等特例（Finding 2）：裸"幂等"是技术实现断言，不应因文本含提交/失败/保存被业务级放行；
    # 但 evidence 明确写出"重复提交不产生重复记录"等幂等业务规则时，可作为业务级断言保留。
    # 不误伤纯业务级规则（权限/状态/边界/校验）。
    tech_assertion = _detect_tech_derived_assertion(assertion)
    if tech_assertion and not _is_business_level_rule_only(assertion, tech_assertion):
        tech_supported = _evidence_supports_tech_assertion(evidence, tech_assertion) or any(
            ref in tech_source_refs for ref in src_refs
        )
        # 幂等业务规则放行：evidence 明确写出幂等业务规则时，幂等断言可作业务级保留
        if not tech_supported and tech_assertion == "幂等":
            tech_supported = bool(_IDEMPOTENCE_BUSINESS_RULE_RE.search(evidence))
        if not tech_supported:
            return _route_to_needs_spec(
                ver,
                new_verdict="undefined",
                reason=f"R3 技术派生断言「{tech_assertion}」未被技术方案支撑",
                unsupported=[tech_assertion],
                review_issue_type="case_wrong",
            )

    # R6：外部目录/"等"不完整 + 唯一具体映射断言 → needs_spec
    external = _detect_external_mapping_assertion(assertion, evidence)
    if external:
        return _route_to_needs_spec(
            ver,
            new_verdict="ungrounded",
            reason=f"R6 外部目录/「等」无完整映射，唯一具体断言「{external}」不成立",
            unsupported=[external],
            review_issue_type="verify_uncertain",
        )

    # R5：低信任来源单独支撑高精度 oracle → needs_spec（无论 evidence 是否含，
    # 来源本身低信任就不能支撑高精度 oracle）。取用例所有 step source_ref 中最低信任
    # （trust 数值最大）者判定——多 step 场景任一 step 来自低信任来源即应触发，
    # 不能只查首个 step（否则低信任来源支撑的高精度 oracle 在非首 step 会漏进 main）。
    if _is_high_precision_oracle(assertion):
        trust = _lowest_trust(src_refs, source_trust)
        if trust is not None and trust >= _LOW_TRUST_THRESHOLD:
            return _route_to_needs_spec(
                ver,
                new_verdict="ungrounded",
                reason=f"R5 低信任来源(trust={trust})单独支撑高精度 oracle",
                review_issue_type="verify_uncertain",
            )

    return ver


def _lowest_trust(src_refs: list[str], source_trust: dict[str, int]) -> int | None:
    """取 src_refs 中最低信任（数值最大）者。无任何 ref 命中时返回 None（保守不降权）。"""
    trusts = [source_trust[r] for r in src_refs if r in source_trust]
    if not trusts:
        return None
    return max(trusts)


def _merge_evidence(source_quote: str, provenance_excerpt: str, prd_evidence: str | None) -> str:
    """合并生成期 source_quote + 溯源摘录 provenance_excerpt + verify 期 prd_evidence 为单一证据池。"""
    parts = [source_quote or ""]
    if provenance_excerpt:
        parts.append(str(provenance_excerpt))
    if prd_evidence:
        parts.append(str(prd_evidence))
    return " ".join(p for p in parts if p)


def _detect_task_status_display_layer_mismatch(
    assertion: str,
    evidence: str,
    ver: CaseVerification,
) -> str | None:
    """R4 同层/同实体补充：任务列表展示文案不应用业务状态机名直接反驳。

    该 guard 只处理非 cross-section、无 refs 的 conflict。若 case 侧是在 UI/列表执行状态列
    上断言「部分失败」，而 PRD 侧证据是业务状态机名称「提交完成-有失败」，说明比较对象处在
    不同抽象层。正确策略是撤销硬 conflict、降到 needs_spec 等同层证据；不直接改 main。
    """
    if ver.verdict != "conflict":
        return None
    if ver.cross_section_conflict or ver.conflicting_refs:
        return None
    # 若 verify LLM 已明确判定同一实体，确定性词法补丁不得覆盖 LLM 的结构化判断。
    if ver.same_entity is True:
        return None

    case_text = " ".join(
        [
            assertion or "",
            ver.conflict_subject_case or "",
            " ".join(ver.unsupported_assertions or []),
        ]
    )
    prd_text = " ".join([evidence or "", ver.rationale or "", ver.conflict_subject_prd or ""])

    if not _TASK_STATUS_PARTIAL_STATE_RE.search(prd_text):
        return None
    if not _TASK_STATUS_DISPLAY_PARTIAL_RE.search(case_text):
        return None
    # 如果 case 自己断言的是业务/状态机名称，而不是列表/执行状态列展示，则是真同层冲突。
    if _TASK_STATE_NAME_PARTIAL_RE.search(assertion or "") and not _TASK_STATUS_DISPLAY_PARTIAL_RE.search(
        assertion or ""
    ):
        return None
    return "状态展示层与业务状态机命名不同，非同层同实体 conflict，待补同层 UI/状态展示证据"


def _canonical_count_unit(unit: str) -> str:
    """把同一业务单位的不同表述归一化，用于核对 conflict basis 是否锚定在 case 中。"""
    compact = re.sub(r"\s+", "", unit or "").lower()
    if compact in {"创意组", "组"}:
        return "组"
    if compact in {"素材", "视频"}:
        return "素材"
    if compact in {"区县", "地区字符串", "地区"}:
        return "地区"
    if compact in {"query参数", "查询参数", "宏参数"}:
        return "参数"
    return compact


def _extract_count_unit_atoms(text: str) -> list[tuple[str, str, str]]:
    """提取文本里的“数字 + 业务单位”事实片段。

    返回 ``(原片段, 数字, 归一化单位)``。只服务于 conflict basis 锚定检查，不做完整事实解析。
    """
    atoms: list[tuple[str, str, str]] = []
    for match in _NUM_UNIT_RE.finditer(text or ""):
        atoms.append((match.group(0), match.group("count"), _canonical_count_unit(match.group("unit"))))
    return atoms


def _detect_unanchored_numeric_conflict_assertion(assertion: str, ver: CaseVerification) -> str | None:
    """R4：verify 的 hard conflict 依据必须锚定在 case 真实断言中。

    只处理窄形态：非 cross-section conflict 中，unsupported_assertions 带有可核查的
    “数字 + 业务单位”事实片段，但该数字+单位组合没有出现在 case 断言文本里。此时更可能是
    verify 幻觉/误读了 case，而不是 case 与 PRD 真冲突，应撤销 hard conflict、转待复核。
    """
    if ver.verdict != "conflict":
        return None
    if ver.cross_section_conflict or ver.conflicting_refs:
        return None
    if not ver.unsupported_assertions:
        return None

    assertion_pairs = {(count, unit) for _, count, unit in _extract_count_unit_atoms(assertion)}
    if not assertion_pairs:
        return None
    for unsupported in ver.unsupported_assertions:
        for raw_atom, count, unit in _extract_count_unit_atoms(unsupported):
            if (count, unit) not in assertion_pairs:
                return f"verify conflict 依据未锚定在用例断言：{raw_atom}"
    return None


def _detect_geo_selection_interface_layer_mismatch(
    assertion: str,
    source_quote: str,
    ver: CaseVerification,
) -> str | None:
    """R4 同层补充：地理位置 UI 勾选上限不应用接口收录上限直接反驳。

    PRD 同时可能存在两类约束：
    - UI 交互层：区县选择器最多选 1000 个，第 1001 个起阻止勾选/红框提示。
    - 接口/载荷层：接口层单次最多收录 200 条地区字符串，超出截断。

    二者可以并存；verify 若拿接口层 200 条截断反驳 UI 层 1000 个勾选上限，属于跨层误判。
    但如果 case 自己断言的是接口层可收录 1000 条地区字符串，则仍是同层真冲突，不降级。
    """
    if ver.verdict != "conflict":
        return None
    if ver.cross_section_conflict or ver.conflicting_refs:
        return None

    case_text = " ".join(
        [
            assertion or "",
            source_quote or "",
            ver.conflict_subject_case or "",
            " ".join(ver.unsupported_assertions or []),
        ]
    )
    # 只用 PRD 侧 subject/evidence 判反驳层，避免 rationale 中复述 case 文本造成自污染。
    prd_basis_text = " ".join([ver.conflict_subject_prd or "", ver.prd_evidence or ""])

    if not _GEO_UI_SELECTION_LIMIT_RE.search(case_text):
        return None
    if not _GEO_INTERFACE_PAYLOAD_LIMIT_RE.search(prd_basis_text):
        return None
    return "地理位置 UI 勾选上限与接口层地区字符串收录上限是不同抽象层，不能互相作为 hard conflict 反驳"


def _detect_link_entity_mismatch(
    assertion: str,
    source_quote: str,
    ver: CaseVerification,
) -> str | None:
    """R4 同层/同实体补充：投放链接与监测链接不能互相反驳。

    投放链接是批创表单内按投放方式过滤的可选链接列表；监测链接是 IAP/IAA
    预置宏参数链接并在提交时自动绑定。两者都叫“链接”，但测试 oracle 的实体不同。
    当 verify 把其中一个实体的规则拿来反驳另一个实体时，撤销硬 conflict，转入 needs_spec
    待同实体证据复核。
    """
    if ver.verdict != "conflict":
        return None
    if ver.cross_section_conflict or ver.conflicting_refs:
        return None
    # 若 verify LLM 已明确判定同一实体，确定性词法补丁不得覆盖 LLM 的结构化判断。
    if ver.same_entity is True:
        return None

    case_text = " ".join(
        [
            assertion or "",
            source_quote or "",
            ver.conflict_subject_case or "",
            " ".join(ver.unsupported_assertions or []),
        ]
    )
    # 只用 PRD 侧 subject/evidence 判反驳实体，避免 rationale 中复述 case 文本造成自污染。
    prd_basis_text = " ".join([ver.conflict_subject_prd or "", ver.prd_evidence or ""])

    case_is_delivery = bool(_DELIVERY_LINK_ENTITY_RE.search(case_text))
    case_is_monitoring = bool(_MONITORING_LINK_ENTITY_RE.search(case_text))
    prd_is_delivery = bool(_DELIVERY_LINK_ENTITY_RE.search(prd_basis_text))
    prd_is_monitoring = bool(_MONITORING_LINK_ENTITY_RE.search(prd_basis_text))

    if case_is_delivery and prd_is_monitoring and not prd_is_delivery:
        return "投放链接与监测链接是不同实体，不能用监测链接自动绑定规则反驳投放链接空态/选择规则"
    if case_is_monitoring and prd_is_delivery and not prd_is_monitoring:
        return "监测链接与投放链接是不同实体，不能用投放链接列表选择规则反驳监测链接自动绑定规则"
    return None


def _query_param_counts_from_evidence(evidence: str) -> set[int]:
    """从证据中的完整 URL 提取 query 参数名数量。

    用 URL parser 而不是字符串分割；同一参数重复出现按一个参数名计算，避免重复值制造假数量。
    没有 query 的 URL 不参与判断。
    """
    counts: set[int] = set()
    for match in _URL_RE.finditer(evidence or ""):
        query = urlsplit(match.group(0)).query
        if not query:
            continue
        # source_quote / prd_evidence 常会把长 URL 写成 ?... / ?…；这种不是完整证据，
        # 不能拿截断后的少量参数制造假计数。
        if "..." in query or "…" in query:
            continue
        names = {name for name, _ in parse_qsl(query, keep_blank_values=True) if name}
        if names:
            counts.add(len(names))
    return counts


def _detect_query_param_count_conflict(assertion: str, evidence: str) -> str | None:
    """R7/R2：断言中的 query/宏参数数量必须被证据支撑。

    只处理断言明确写出「N 个宏参数/查询参数」的高精度数量 oracle：
    - 证据有完整 URL query：按参数名集合计数，数量不一致则分流。
    - 证据没有完整 URL，但明文写出同一数量：视为有支撑。
    - 两者都没有：该精确数量缺证据，不能留在 main。
    """
    asserted = {int(m.group("count")) for m in _QUERY_PARAM_COUNT_RE.finditer(assertion or "")}
    if not asserted:
        return None
    actual = _query_param_counts_from_evidence(evidence)
    if actual:
        mismatches = sorted(n for n in asserted if n not in actual)
        if mismatches:
            mismatch_text = ",".join(str(n) for n in mismatches)
            actual_text = ",".join(str(n) for n in sorted(actual))
            return f"宏参数数量不一致：断言{mismatch_text}个，证据URL为{actual_text}个"
        return None
    evidence_counts = {int(m.group("count")) for m in _QUERY_PARAM_COUNT_RE.finditer(evidence or "")}
    if asserted & evidence_counts:
        return None
    asserted_text = ",".join(str(n) for n in sorted(asserted))
    return f"宏参数数量缺少可核验证据：断言{asserted_text}个，证据未提供完整URL或相同数量声明"


def _detect_template_character_limit_conflict(assertion: str, evidence: str) -> str | None:
    """R7：模板字符硬上限不能被半角 0.5 字显示算法放宽。

    只处理窄形态：用例断言模板场景中 N 个半角字符可保存/未超限，证据明确写出
    “每条模板 M 字符”硬上限，且 N > M。普通标题文案的半角字数展示规则不受影响。
    """
    if not assertion or not evidence:
        return None
    if not _TEMPLATE_ASSERTION_CONTEXT_RE.search(assertion):
        return None
    limit_match = _TEMPLATE_CHAR_LIMIT_RE.search(evidence)
    if not limit_match:
        return None
    if not _HALFWIDTH_ACCEPT_RE.search(assertion):
        return None
    limit = int(limit_match.group("limit"))
    for count_match in _HALFWIDTH_CHAR_COUNT_RE.finditer(assertion):
        count = int(count_match.group("count"))
        if count > limit:
            return f"模板字符上限冲突：证据为{limit}字符，断言{count}个半角字符未超上限/可保存"
    return None


def _iter_parameterized_copy_templates(evidence: str) -> list[str]:
    """从证据中提取含独立 N 占位的文案模板。

    优先使用引号/加粗这类明确边界，避免从整段 PRD 句子里截出过宽模板造成误放行。
    """
    templates: list[str] = []
    seen: set[str] = set()
    for match in _QUOTED_COPY_RE.finditer(evidence or ""):
        template = match.group(1).strip()
        if _COPY_PARAM_PLACEHOLDER_RE.search(template) and template not in seen:
            templates.append(template)
            seen.add(template)
    for match in _MARKDOWN_BOLD_COPY_TEMPLATE_RE.finditer(evidence or ""):
        template = match.group(1).strip()
        if _COPY_PARAM_PLACEHOLDER_RE.search(template) and template not in seen:
            templates.append(template)
            seen.add(template)
    return templates


def _parameterized_copy_template_matches(template: str, concrete_copy: str) -> bool:
    """判断 PRD 模板文案是否支撑具体测试数据实例。

    仅把独立 ``N`` 当数字占位符；模板中其他字符必须匹配。空白做宽松处理，
    支持 PRD 写「已选N」而用例写「已选 3」的常见形态。
    """
    if not template or not concrete_copy:
        return False
    if not _COPY_PARAM_PLACEHOLDER_RE.search(template):
        return False

    parts: list[str] = []
    last = 0
    for match in _COPY_PARAM_PLACEHOLDER_RE.finditer(template):
        parts.append(re.escape(template[last : match.start()]))
        parts.append(r"\s*[0-9０-９]+\s*")
        last = match.end()
    parts.append(re.escape(template[last:]))
    pattern = "".join(parts).replace(r"\ ", r"\s*")
    return bool(re.fullmatch(pattern, concrete_copy.strip()))


def _evidence_supports_parameterized_copy(evidence: str, concrete_copy: str) -> bool:
    """R2：PRD 参数化文案模板可支撑数字化实例。

    例如 PRD 写「已更新 N 个账户」，用例测试数据为 5 个账户时，
    「已更新 5 个账户」应视为同一可执行 oracle，而不是 fake copy。
    """
    return any(
        _parameterized_copy_template_matches(template, concrete_copy)
        for template in _iter_parameterized_copy_templates(evidence)
    )


def _evidence_supports_tech_assertion(evidence: str, tech_assertion: str) -> bool:
    """R3：判断技术形态断言是否被当前证据直接支撑。

    这里保持窄口径：普通“自动同步”不能支撑 worker/cron/轮询；但 PRD 明确写
    “每天凌晨遍历/拉取/执行”时，足以支撑“定时任务”这个调度类 oracle。
    """
    if _evidence_supports(evidence, tech_assertion):
        return True
    if tech_assertion == "定时任务":
        return bool(_SCHEDULED_TASK_EVIDENCE_RE.search(evidence or ""))
    return False


def _evidence_supports(evidence: str, assertion_fragment: str) -> bool:
    """R2/R3 辅助：判断证据池是否已支撑该具体 oracle / 技术断言（有据）。

    - 状态码/表名：evidence 含相同字面值即视为有据。
    - API method+path（Finding 1）：evidence 须含【相同完整 path】，不能仅含 method 子串
      （"POST /api/accounts/bulk-assign" 不被 "POST /api/accounts/list" 支撑）。
    - payload 字段（Finding 1）：evidence 须含【每个】字段名，缺一不支撑。
    - 具体文案：evidence 含该文案即视为有据。
    - 技术断言泛词（如「worker」）：evidence 含该词即视为有据。
    assertion_fragment 形如 ``POST /api/accounts/bulk-assign`` / ``payload字段ids, owner`` /
    ``落库order_detail`` / ``具体文案「立即提交」`` / ``HTTP 409`` / ``幂等``。
    """
    if not evidence or not assertion_fragment:
        return False
    # API method + path：method + path 必须【精确相等】（二审 F1-endpoint）。
    # 不用普通子串/前缀匹配——"/api/accounts/list" 不被 "/api/accounts/listing" 支撑
    # （list 是 listing 前缀但二者是不同 endpoint）。从 assertion/evidence 都提取 METHOD + path
    # token 比对，安全边界只允许明确设计：断言 path 与 evidence 某个 path 完全相同。
    m = re.match(r"^(GET|POST|PUT|DELETE|PATCH)\s+(\/\S+)", assertion_fragment, re.I)
    if m:
        a_method, a_path = m.group(1).upper(), m.group(2)
        for em in _API_METHOD_PATH_RE.finditer(evidence):
            if em.group(1).upper() == a_method and em.group(2) == a_path:
                return True
        return False
    # payload 字段（三审 P1 + 四审 P1）：atom 格式 "payload字段{ctx}:{fields}"，
    # ctx 为 request/response/generic。按【同上下文】从 evidence 提取字段集合精确比对
    # （顺序不敏感）——请求体 code 不能支撑响应体 code。identifier token 精确匹配，不 substring。
    m = re.match(r"^payload字段(\w+):(.+)$", assertion_fragment)
    if m:
        ctx = m.group(1)
        # 字段分隔符仅 [,，和]（与 _FIELD_LIST_RE 对齐，不含裸 \s）——audit 指出 evidence 侧
        # 用 \s 会把 "ids owner"（纯空格无"和"）误拆成两字段偏向支撑；收紧后纯空格分隔不拆，
        # 偏向不支撑（更严，防漏判）。
        fields = [f.strip() for f in re.split(r"[,，和]+", m.group(2)) if f.strip()]
        # 按 ctx 分组从 evidence 的 payload 上下文里提取字段集合
        ev_fields_by_ctx: dict[str, set[str]] = {"request": set(), "response": set(), "generic": set()}
        for fm in _PAYLOAD_FIELD_RE.finditer(evidence):
            fctx = _payload_context_of(fm.group("ctx"))
            for ef in re.split(r"[,，和]+", fm.group("fields")):
                ef = ef.strip()
                if ef:
                    ev_fields_by_ctx[fctx].add(ef.lower())
        # 同 ctx 字段集合精确比对；同 ctx 为空时 generic 兜底（generic 上下文可跨请求/响应）
        same_ctx_fields = ev_fields_by_ctx.get(ctx, set())
        if same_ctx_fields:
            return all(f.lower() in same_ctx_fields for f in fields)
        if ctx != "generic" and ev_fields_by_ctx.get("generic"):
            return all(f.lower() in ev_fields_by_ctx["generic"] for f in fields)
        # 兜底：atom 是 generic 且 evidence 也无 payload 上下文时，用 identifier 边界匹配。
        # 注意：atom 带明确 request/response ctx 时不走 ident_match——否则会跨上下文误匹配
        # （请求体 code 不能支撑响应体 code，四审 P1）。
        if ctx == "generic":

            def _ident_match(field: str) -> bool:
                pat = re.compile(rf"(?<![a-zA-Z0-9_]){re.escape(field)}(?![a-zA-Z0-9_])", re.I)
                return bool(pat.search(evidence))

            return all(_ident_match(f) for f in fields)
        # atom 带明确 ctx 但 evidence 无同 ctx 也无 generic → 不支撑
        return False
    # 提取 assertion_fragment 里的核心字面值（引号内文案 / 落库后的表名 / 状态码数字）
    m = re.search(r"[「『\"']([^」』\"']+)[」』\"']", assertion_fragment)
    if m:
        copy = m.group(1)
        return copy in evidence or _evidence_supports_parameterized_copy(evidence, copy)
    m = re.search(r"落库([a-z_][a-z0-9_]*)", assertion_fragment, re.I)
    if m:
        return m.group(1) in evidence.lower()
    m = re.search(r"\d{3}", assertion_fragment)
    if m:
        return m.group(0) in evidence
    return assertion_fragment in evidence


def _detect_fake_oracle(text: str) -> str | None:
    """R2：检测无据的高精度 oracle，返回首个命中的断言片段（向后兼容，单 atom）。"""
    atoms = _detect_fake_oracles(text)
    return atoms[0] if atoms else None


def _detect_fake_oracles(text: str) -> list[str]:
    """R2：收集【所有】高精度 oracle atom（二审 P1 多 atom 漏判修复）。

    不再只返回首个——一条用例可能同时含多个高精度 oracle（如 "POST /api/x 请求体包含 ids"
    同时有 API endpoint atom 和 payload 字段 atom），任一 atom 无 evidence 支撑即应分流。
    atom 类型：HTTP 状态码 / DB 表名 / payload 字段集合 / API method+path / 具体文案。
    """
    atoms: list[str] = []
    # HTTP 状态码
    for m in _HTTP_STATUS_RE.finditer(text):
        atoms.append(m.group(0))
    # DB 表名/字段
    for m in _DB_TABLE_RE.finditer(text):
        atoms.append(f"落库{m.group(1)}")
    # payload 字段（四审 P1：用 finditer 收集【所有】字段片段，不只取第一段；atom 带上下文
    # 类型 request/response/generic，evidence 按同上下文精确字段集合匹配）。
    if _PAYLOAD_RE.search(text):
        found_any = False
        for fm in _PAYLOAD_FIELD_RE.finditer(text):
            ctx = _payload_context_of(fm.group("ctx"))
            fields_raw = fm.group("fields").strip()
            if fields_raw:
                atoms.append(f"payload字段{ctx}:{fields_raw}")
                found_any = True
        if not found_any:
            atoms.append("payload")
    # API method + path（完整片段）
    for m in _API_METHOD_PATH_RE.finditer(text):
        atoms.append(f"{m.group(1).upper()} {m.group(2)}")
    # API 契约泛信号（无 method+path 的，如 X-Idempotency / 响应结构）
    for m in _API_CONTRACT_RE.finditer(text):
        fragment = m.group(0)
        # 避免与 method+path atom 重复（method+path 已含 METHOD）
        if not any(fragment in a for a in atoms):
            atoms.append(fragment)
    # 具体文案（toast/错误提示等，局部绑定）
    quote = _detect_fake_copy_quote(text)
    if quote:
        atoms.append(quote)
    return atoms


def _detect_fake_copy_quote(text: str) -> str | None:
    """R2 文案引号局部绑定：取文案上下文关键词后方最近的引号内容。

    扫描所有 _FAKE_COPY_CONTEXT 关键词出现位置，在每个关键词后方（同句，距离 ≤30 字符）
    找最近的引号；该引号内容若非业务取值/计算式/UI 标签，则判为 fake 文案 oracle。
    """
    low = text.lower()
    # 收集所有上下文关键词的结束位置
    ctx_ends: list[int] = []
    for kw in _FAKE_COPY_CONTEXT:
        start = 0
        while True:
            idx = low.find(kw, start)
            if idx < 0:
                break
            ctx_ends.append(idx + len(kw))
            start = idx + len(kw)
    if not ctx_ends:
        return None

    quotes = list(_QUOTED_COPY_RE.finditer(text))
    if not quotes:
        return None

    # 对每个上下文位置，扫描其【后方窗口内(≤30字符)的所有引号】，跳过 UI 标签/业务值/
    # 计算式后继续找下一个——避免"toast 在「确认操作」按钮旁显示「操作失败」"因最近引号是
    # 按钮名就 break 漏掉后续 toast 文案（任务 07-02 第五轮 false negative 修复）。
    # 候选保存 (distance, inner, start, end)——直接用候选 span 做 UI 标签窗口检查，
    # 不再用 _find_quote_span(inner)（同文案重复时会拿错 span）。
    candidates: list[tuple[int, str, int, int]] = []
    for ce in ctx_ends:
        for q in quotes:
            if q.start() < ce:
                continue
            dist = q.start() - ce
            if dist > 30:
                break  # 超出窗口，后续引号更远，停止本上下文扫描
            candidates.append((dist, q.group(1), q.start(), q.end()))
    if not candidates:
        return None
    # 按距离排序，最近的优先；逐个检查，跳过不合格的继续找下一个
    candidates.sort(key=lambda x: x[0])
    for _, inner, qstart, qend in candidates:
        if _is_business_value(inner) or _CALC_RE.search(inner):
            continue
        if _is_ui_label_quote(text, qstart, qend):
            continue
        return f"具体文案「{inner}」"
    return None


# UI 元素标签上下文：引号前后出现这些词时，该引号是 UI 元素名（按钮/字段/Tab/选项）非文案断言。
_UI_LABEL_CONTEXT: tuple[str, ...] = (
    "按钮",
    "Tab",
    "tab",
    "选项",
    "字段",
    "下拉",
    "点击",
    "选择",
    "切换",
    "勾选",
    "输入框",
    "模式",
    "segmented",
    "菜单",
    "链接",
    "控件",
    "图标",
)


def _is_ui_label_quote(text: str, start: int, end: int) -> bool:
    """判断引号（位于 text[start:end]）是否是 UI 元素标签（按钮名/字段名/Tab名等）。

    只看引号【紧贴外侧】前后各 4 字符——UI 标签的 UI 元素词紧邻引号外侧
    （如「授权成功」按钮、"确定"字段）；toast/错误文案引号紧邻的是动词/句末
    （如显示「操作失败」、展示「名称重复」），外侧 4 字符无 UI 元素词。
    任务 07-02 第五轮：前窗 6 字符会把"按钮旁显示「文案」"里前一个引号的"按钮"
    算进本引号前窗致误判，收窄到 4 + 仅看紧贴外侧可解。
    """
    pre = text[max(0, start - 4) : start]
    post = text[end : min(len(text), end + 4)]
    return any(k in pre for k in _UI_LABEL_CONTEXT) or any(k in post for k in _UI_LABEL_CONTEXT)


def _is_business_value(inner: str) -> bool:
    """引号内容是否为业务取值/测试数据（非 fake 文案 oracle）。

    - 纯数字（500/471）、纯字母数字无中文（test/xyz/1234567890/CBO 直投无中文部分时）；
    - 含业务枚举大写缩写（ROI/IAA/IAP/CBO 等）；
    - 单字/短语但无文案语义（由上下文已门控，这里只做字面排除）。
    注意：中文业务枚举如「CBO直投」含中文，不命中 _BUSINESS_VALUE_RE——靠上下文门控
    （无 toast/提示文案 上下文就不判 fake）。这里只拦纯 ASCII 取值。
    """
    if not inner:
        return True
    if _BUSINESS_VALUE_RE.match(inner):
        return True
    return False


def _detect_tech_derived_assertion(text: str) -> str | None:
    """R3：检测技术派生断言（接口契约/幂等/worker/cron/轮询频率等），返回命中片段。

    用【最长匹配】：强信号与泛词都可能命中时，返回最长者——"指数退避重试"会返回"指数退避"
    而非"重试"，避免泛词抢占后经 _is_business_level_rule_only 被业务词放行（audit P1-3 漏洞）。
    """
    m = _API_CONTRACT_RE.search(text)
    if m:
        return m.group(0)
    m = _SCHEDULE_RE.search(text)
    if m:
        return m.group(0)
    low = text.lower()
    # 合并强信号 + 泛词，按长度降序取首个命中（最长匹配）
    all_signals = _TECH_STRONG_SIGNALS + _TECH_GENERIC_SIGNALS
    hits = [sig for sig in all_signals if sig in low]
    if not hits:
        return None
    return max(hits, key=len)


def _is_business_level_rule_only(text: str, tech_assertion: str) -> bool:
    """判断该用例是否"仅是业务级规则，技术派生信号是误判"。

    - 具体 API path / 调度数值断言：硬技术派生，不算业务级（返回 False）。
    - 强技术信号（指数退避/熔断/分布式锁/worker/cron 等）：命中即判技术断言，不算业务级
      （返回 False）——避免"指数退避重试+业务词"被误放行（audit P1-3 漏洞）。
    - 泛词（重试/幂等）出现在纯业务描述里（如"失败后可重试提交"）：若文本整体是业务级
      （权限/状态/边界/校验），判业务级放行。
    """
    # 具体 API path / 调度数值是硬技术派生，不算业务级
    if _API_CONTRACT_RE.search(tech_assertion) or _SCHEDULE_RE.search(tech_assertion):
        return False
    # 强技术信号不算业务级
    if tech_assertion in _TECH_STRONG_SIGNALS:
        return False
    return _is_business_level_rule(text)


def _detect_external_mapping_assertion(assertion: str, source_quote: str) -> str | None:
    """R6：外部目录/"等"不完整 + 唯一具体映射断言 → 返回具体映射片段。

    "等"/外部目录信号来自 PRD 引文（source_quote，表示 PRD 只给了非完整枚举），
    唯一具体映射断言来自用例（assertion）。二者同时满足 → 该断言无完整映射支撑。
    """
    return unsupported_unique_fact_assertion(assertion, source_quote)
