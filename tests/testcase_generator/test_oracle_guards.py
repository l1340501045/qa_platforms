"""Oracle Guard 对齐测试（任务 07-02）。

8 个 guard 的失败优先单测，对应 PRD R1-R8：
- R1 澄清信号分流（不进 main，保留到 needs_spec）
- R2 Fake Oracle Guard（无据的具体 toast/状态码/payload 不进 main）
- R3 无技术方案时禁写技术派生断言（不误伤业务级权限/安全/边界/状态）
- R4 cross_section_conflict=True 且 refs 非空 → 分流 + 保留证据
- R5 低信任证据不能单独支撑高精度 oracle
- R6 外部目录/"等"不完整时不生成唯一具体映射断言
- R7 字数边界确定性（9 半角 = 4.5，向上取整 5）
- R8 指标不靠删数据美化（不直接删 ungrounded/undefined）
"""

from __future__ import annotations

from src.testcase_generator.schemas.test_case import (
    CaseVerification,
    CrossSectionConflictRef,
)
from src.testcase_generator.stages.verify.verifier import (
    VerifyCase,
    apply_oracle_guards,
)
from src.testcase_generator.stages.write_cases.length_check import (
    char_count_halfwidth_units,
    round_half_up,
)

# ── 共用构造 helper ────────────────────────────────────────────────────────


def _vc(
    verdict: str = "grounded",
    bucket: str = "main",
    *,
    rationale: str = "有 PRD 支撑",
    cross_section_conflict: bool = False,
    conflicting_refs: list[CrossSectionConflictRef] | None = None,
    unsupported_assertions: list[str] | None = None,
    prd_evidence: str | None = None,
) -> CaseVerification:
    return CaseVerification(
        verdict=verdict,
        bucket=bucket,
        rationale=rationale,
        cross_section_conflict=cross_section_conflict,
        conflicting_refs=conflicting_refs or [],
        unsupported_assertions=unsupported_assertions or [],
        prd_evidence=prd_evidence,
    )


def _case(
    title: str,
    *,
    expected: str = "",
    source_quote: str | None = None,
    source_ref: str | None = None,
    trust_level: int = 1,
    verification: CaseVerification | None = None,
) -> VerifyCase:
    step: dict = {
        "action": title,
        "input_data": "",
        "expected_result": expected or title,
    }
    if source_quote is not None:
        step["source_quote"] = source_quote
    if source_ref is not None:
        step["source_ref"] = source_ref
    return VerifyCase(
        case_id="TC-1",
        feature_id="F1",
        title=title,
        steps=[step],
        expected_results=[expected or title],
        provenance_excerpt=source_quote,
    )


def _url_with_query_param_count(count: int) -> str:
    params = "&".join(f"p{i}=__P{i}__" for i in range(1, count + 1))
    return f"https://example.test/click/hash?{params}"


# ── R1：澄清信号分流 ──────────────────────────────────────────────────────


def test_r1_clarification_signal_routed_out_of_main():
    """标题/预期含「需求待确认/待确认/PRD未定义」时不得进 main，应分流到 needs_spec。"""
    case = _case("待确认：登录失败是否锁定账户", expected="需求待确认：锁定策略 PRD 未定义")
    ver = _vc(verdict="grounded", bucket="main")

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket != "main"
    assert guarded["TC-1"].bucket == "needs_spec"
    # 风险保留（不删除），rationale 标注分流原因
    assert "待确认" in guarded["TC-1"].rationale or "澄清" in guarded["TC-1"].rationale


def test_r1_clarification_signal_variants_all_routed():
    """多种澄清信号措辞都应被识别。"""
    signals = ["【需求待确认】", "PRD未定义", "无确定断言", "待确认"]
    for sig in signals:
        case = _case(f"{sig}字段校验规则", expected=f"结果{sig}")
        ver = _vc(verdict="grounded", bucket="main")
        guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())
        assert guarded["TC-1"].bucket == "needs_spec", f"信号「{sig}」未被分流"


def test_vague_only_expected_result_routed_out_of_main():
    """纯模糊预期无法执行，不应作为 grounded/main 稳定用例。"""
    case = _case("入口页展示校验", expected="页面正常显示，信息正确")
    ver = _vc(verdict="grounded", bucket="main")

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "needs_spec"
    assert guarded["TC-1"].verdict == "undefined"
    assert guarded["TC-1"].review_issue_type == "case_wrong"
    assert any("页面正常显示" in item for item in guarded["TC-1"].unsupported_assertions)


def test_vague_wording_with_concrete_observable_detail_stays_main():
    """带具体字段/状态/数值的预期可执行，不因含“正常显示”被误杀。"""
    case = _case(
        "账户授权列表展示",
        expected="列表正常显示账户名称、账户ID，授权状态为已授权",
        source_quote="列表展示账户名称、账户ID、授权状态",
    )
    ver = _vc(verdict="grounded", bucket="main", prd_evidence="列表展示账户名称、账户ID、授权状态")

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "main"


# ── R2：Fake Oracle Guard ──────────────────────────────────────────────────


def test_r2_fake_oracle_http_status_without_evidence_routed():
    """PRD 只写约束时，具体 HTTP 状态码断言无据 → 不进 main。"""
    case = _case(
        "提交订单失败返回 409",
        expected="接口返回 HTTP 409 Conflict",
        source_quote="提交失败应阻断",  # PRD 只说"阻断"，没说状态码
    )
    ver = _vc(verdict="grounded", bucket="main")

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket != "main"
    # unsupported_assertions 记录被分流的断言（风险保留，不删）
    assert any("409" in a for a in guarded["TC-1"].unsupported_assertions)


def test_r2_fake_oracle_business_level_kept():
    """业务级"应校验失败/应阻断提交"无状态码时仍可进 main（允许业务级预期）。"""
    case = _case(
        "提交订单必填项缺失阻断提交",
        expected="阻断提交并提示错误",  # 业务级，无具体文案/状态码
        source_quote="必填项缺失应阻断提交",
    )
    ver = _vc(verdict="grounded", bucket="main")

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "main"


def test_r2_fake_oracle_payload_without_evidence_routed():
    """无据的具体 payload/表名断言不进 main。"""
    case = _case(
        "落库到 order_detail 表",
        expected="写入 order_detail 表的 amount 字段",
        source_quote="提交成功后保存订单",
    )
    ver = _vc(verdict="grounded", bucket="main")

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket != "main"


# ── R2 收窄（任务 07-02 第三轮）：业务枚举/裸数字/计算式/按钮字段名不误杀 ──
# 以下负向测试【故意不给 evidence 支撑】——目的是验证 R2 的【识别】环节不过宽：
# 即使证据池不含这些值，R2 也不应把业务枚举/裸数字/计算式/按钮字段名判为 fake oracle。
# 若 R2 把它们识别为 fake，即使无证据也应当分流——但它们是合法业务内容，不应被识别。


def test_r2_business_enum_in_quotes_not_routed():
    """业务枚举（CBO直投/付费ROI/IAA/IAP）带引号不触发 R2——是业务取值，非 fake 文案。

    即使 evidence 不含该值，R2 也不应把业务枚举当 fake oracle 识别。
    """
    for name in ("CBO直投", "付费ROI", "IAA", "IAP"):
        case = _case(
            f"投放方式选择「{name}」",
            expected=f"下拉显示「{name}」选项",
            source_quote="投放方式支持多种类型",  # evidence 故意不含具体枚举
        )
        ver = _vc(verdict="grounded", bucket="main")
        guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())
        assert guarded["TC-1"].bucket == "main", f"业务枚举「{name}」被 R2 误杀"


def test_r2_bare_three_digit_not_routed():
    """裸三位数字（TP-471 的 471、容量 500/521/522）不触发 R2。

    无 HTTP/状态码/返回码/响应码上下文的三位数字是业务取值（用例ID/容量/条数），
    不是 HTTP 状态码 oracle。即使 evidence 不含该数字，R2 也不该识别。
    """
    for num in ("471", "500", "521", "522"):
        case = _case(
            f"TP-{num} 验证容量为{num}条",
            expected=f"列表展示{num}条数据",
            source_quote="列表展示数据",  # evidence 故意不含数字
        )
        ver = _vc(verdict="grounded", bucket="main")
        guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())
        assert guarded["TC-1"].bucket == "main", f"裸数字「{num}」被 R2 误杀"


def test_r2_calculation_formula_not_routed():
    """计算式（3 × 2 × 5 = 30、账户数×项目数×广告数）不触发 R2——是业务计算，非文案。"""
    case = _case(
        "批创规模 3 × 2 × 5 = 30",
        expected="生成 30 个广告",
        source_quote="按规模生成广告",  # evidence 故意不含 30
    )
    ver = _vc(verdict="grounded", bucket="main")
    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())
    assert guarded["TC-1"].bucket == "main"


def test_r2_button_and_field_label_not_routed():
    """按钮名/字段名（立即提交/选择账户/添加标题/标题包A）带引号不默认触发 R2。

    是 UI 元素标签，非精确 toast/错误提示文案 oracle。即使 evidence 不含，R2 也不该识别。
    """
    for label in ("立即提交", "选择账户", "添加标题", "标题包A", "测试包_1"):
        case = _case(
            f"点击「{label}」按钮",
            expected=f"触发{label}操作",
            source_quote="点击按钮触发操作",  # evidence 故意不含 label
        )
        ver = _vc(verdict="grounded", bucket="main")
        guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())
        assert guarded["TC-1"].bucket == "main", f"按钮/字段名「{label}」被 R2 误杀"


def test_r2_test_data_value_not_routed():
    """测试数据名/输入值（test/xyz/账户ID 1234567890）不触发 R2——是输入数据，非文案断言。"""
    for val in ("test", "xyz", "1234567890"):
        case = _case(
            f"输入{val}搜索",
            expected=f"展示含{val}的记录",
            source_quote="按关键词搜索",  # evidence 故意不含 val
        )
        ver = _vc(verdict="grounded", bucket="main")
        guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())
        assert guarded["TC-1"].bucket == "main", f"测试数据「{val}」被 R2 误杀"


def test_r2_quoted_copy_still_routed_when_toast_context_without_evidence():
    """正向：toast 提示文案为「xxx」且 evidence 不含 → 仍触发 R2（收窄后保留）。"""
    case = _case(
        "提交失败显示 toast 提示文案",
        expected="toast 提示文案为「操作失败，请重试」",
        source_quote="提交失败应提示",  # evidence 不含具体文案
    )
    ver = _vc(verdict="grounded", bucket="main")
    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())
    assert guarded["TC-1"].bucket != "main"
    assert any("操作失败" in a for a in guarded["TC-1"].unsupported_assertions)


def test_r2_http_status_still_routed_with_context_without_evidence():
    """正向：HTTP 状态码 500 且 evidence 不支持 → 仍触发 R2（需上下文）。"""
    case = _case(
        "接口返回 HTTP 状态码 500",
        expected="HTTP 状态码 500",
        source_quote="提交失败应阻断",  # 无 500
    )
    ver = _vc(verdict="grounded", bucket="main")
    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())
    assert guarded["TC-1"].bucket != "main"


def test_r2_error_message_quoted_still_routed_without_evidence():
    """正向：错误提示/弹窗文案「xxx」且 evidence 不含 → 仍触发 R2。"""
    case = _case(
        "校验失败弹窗文案",
        expected="弹窗文案为「名称重复」",
        source_quote="重名禁止保存",  # evidence 不含具体弹窗文案
    )
    ver = _vc(verdict="grounded", bucket="main")
    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())
    assert guarded["TC-1"].bucket != "main"


def test_r2_parameterized_copy_n_supports_concrete_toast_count():
    """PRD 参数化文案「已更新 N 个账户」可支撑测试数据实例「已更新 5 个账户」。"""
    case = _case(
        "批量修改投放人成功 toast",
        expected="toast 提示文案为「已更新 5 个账户」",
        source_quote="成功 toast「已更新 N 个账户」、关闭弹窗、清空勾选并刷新列表。",
    )
    ver = _vc(verdict="grounded", bucket="main")

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "main"


def test_r2_parameterized_copy_n_supports_chinese_button_count():
    """PRD 参数化 UI 文案「已选 N」可支撑具体勾选数量实例「已选 3」。"""
    case = _case(
        "批量修改投放人底栏文案",
        expected="底栏显示文案为「批量修改投放人（已选 3）」",
        source_quote="表格底栏「批量修改投放人（已选 N）」，N 为当前勾选集合大小。",
    )
    ver = _vc(verdict="grounded", bucket="main")

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "main"


def test_r2_parameterized_copy_n_supports_markdown_bold_template():
    """PRD 用 markdown 加粗表达 UI 文案模板时，也可支撑具体数量实例。"""
    case = _case(
        "批量修改投放人底栏文案",
        expected="底栏显示文案为「批量修改投放人（已选 4）」",
        source_quote="底栏：左侧 **批量修改投放人（已选 N）**",
    )
    ver = _vc(verdict="grounded", bucket="main")

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "main"


def test_r2_parameterized_copy_n_supports_created_task_count():
    """PRD 参数化创建结果文案可支撑由测试数据落成的具体任务数文案。"""
    case = _case(
        "提交全部成功任务数文案",
        expected="弹窗提示文案为「已创建 1 条广告任务」",
        source_quote="弹窗提示『已创建 N 条广告任务』，N = 已选账户数 × 项目数 × 广告数。",
    )
    ver = _vc(verdict="grounded", bucket="main")

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "main"


def test_r2_parameterized_copy_n_does_not_support_unrelated_verb():
    """参数化文案只允许数字占位替换，不允许把「已更新」扩成「已删除」。"""
    case = _case(
        "批量删除账户成功 toast",
        expected="toast 提示文案为「已删除 5 个账户」",
        source_quote="成功 toast「已更新 N 个账户」、关闭弹窗、清空勾选并刷新列表。",
    )
    ver = _vc(verdict="grounded", bucket="main")

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket != "main"
    assert any("已删除" in a for a in guarded["TC-1"].unsupported_assertions)


# ── R2 引号局部绑定（任务 07-02 第四轮）：toast 前的业务枚举不被错选 ──


def test_r2_toast_after_business_enum_selects_toast_not_enum():
    """toast 文案前的业务枚举不被错选——应选 toast 后方的「操作失败，请重试」。

    文案上下文（toast 提示文案）必须与候选引号局部绑定，不能因整段有 toast 就放开
    所有引号从头扫取首个（会取到前面的业务枚举「CBO直投」）。
    """
    case = _case(
        "投放方式为「CBO直投」时提交失败",
        expected="toast 提示文案为「操作失败，请重试」",
        source_quote="投放方式支持CBO直投",  # evidence 支撑 CBO直投，不含 toast 文案
    )
    ver = _vc(verdict="grounded", bucket="main")
    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    # 应触发 R2（toast 文案「操作失败，请重试」无据），且 unsupported 是 toast 文案不是业务枚举
    assert guarded["TC-1"].bucket != "main"
    unsupported = guarded["TC-1"].unsupported_assertions
    assert any("操作失败" in a for a in unsupported), "应检测到 toast 文案「操作失败，请重试」"
    assert not any("CBO直投" in a for a in unsupported), "不应把业务枚举「CBO直投」当 fake 文案"


def test_r2_error_message_after_package_name_selects_error_not_package():
    """错误提示前的包名不被错选——应选错误提示后方的「名称重复」。"""
    case = _case(
        "标题包名称「标题包A」保存失败",
        expected="错误提示为「名称重复」",
        source_quote="标题包名称规则",  # 不含「名称重复」
    )
    ver = _vc(verdict="grounded", bucket="main")
    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket != "main"
    unsupported = guarded["TC-1"].unsupported_assertions
    assert any("名称重复" in a for a in unsupported), "应检测到错误提示「名称重复」"
    assert not any("标题包A" in a for a in unsupported), "不应把包名「标题包A」当 fake 文案"


def test_r2_evidence_supports_business_enum_but_not_toast_still_triggers():
    """evidence 支撑业务枚举但不支撑 toast 文案时，仍应触发 R2 检测 toast。

    不能因第一个业务值（CBO直投）被 evidence 支撑就漏掉真正的 fake toast。
    修复后：检测器选 toast 后方引号（操作失败，请重试），evidence 不支撑 → R2 触发。
    """
    case = _case(
        "投放方式为「CBO直投」时提交失败",
        expected="toast 提示文案为「操作失败，请重试」",
        source_quote="投放方式支持CBO直投",  # 支撑 CBO直投，不支撑 toast 文案
    )
    ver = _vc(verdict="grounded", bucket="main")
    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    # 必须触发 R2——toast 文案无据，不能因 CBO直投 有据就漏判
    assert guarded["TC-1"].bucket != "main"
    assert "R2" in guarded["TC-1"].rationale


# ── R2 局部绑定 false negative（任务 07-02 第五轮）：继续扫描后续引号 ──


def test_r2_same_text_button_and_toast_selects_toast():
    """按钮名与 toast 文案同文案「授权成功」时，应命中 toast 文案而非跳过。

    修复前：上下文后方最近引号是按钮「授权成功」(UI 标签)，跳过后不再找后续 toast 引号
    → false negative。修复后：跳过 UI 标签后继续扫描后续引号，找到 toast「授权成功」。
    注意两处引号 inner 相同，不能用 _find_quote_span(inner) 拿第一次出现的 span。
    """
    case = _case(
        "点击「授权成功」按钮后授权",
        expected="toast 提示文案为「授权成功」",
        source_quote="点击授权",  # 不含「授权成功」
    )
    ver = _vc(verdict="grounded", bucket="main")
    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket != "main"
    assert "R2" in guarded["TC-1"].rationale


def test_r2_toast_beside_button_selects_toast_text():
    """toast 在按钮旁显示「操作失败，请重试」——按钮引号在前，应跳过它命中 toast 文案。

    修复前：上下文后方最近引号是「确认操作」(按钮名 UI 标签)，跳过后 break，漏掉后续
    toast 文案「操作失败，请重试」。修复后：继续扫描找到 toast 文案。
    """
    case = _case(
        "提交失败",
        expected="toast 提示在「确认操作」按钮旁显示「操作失败，请重试」",
        source_quote="提交失败处理",  # 不含 toast 文案
    )
    ver = _vc(verdict="grounded", bucket="main")
    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket != "main"
    unsupported = guarded["TC-1"].unsupported_assertions
    assert any("操作失败" in a for a in unsupported), "应命中 toast 文案「操作失败，请重试」"
    assert not any("确认操作" in a for a in unsupported), "不应把按钮名「确认操作」当 fake 文案"


def test_r2_error_message_beside_field_selects_error_text():
    """错误提示在字段下方展示「名称重复」——字段引号在前，应跳过它命中错误文案。

    修复前：上下文后方最近引号是「标题包名称」(字段名 UI 标签)，跳过后 break，漏掉
    后续错误文案「名称重复」。修复后：继续扫描找到错误文案。
    """
    case = _case(
        "保存失败",
        expected="错误提示：请在「标题包名称」字段下方展示「名称重复」",
        source_quote="保存校验",  # 不含「名称重复」
    )
    ver = _vc(verdict="grounded", bucket="main")
    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket != "main"
    unsupported = guarded["TC-1"].unsupported_assertions
    assert any("名称重复" in a for a in unsupported), "应命中错误文案「名称重复」"
    assert not any("标题包名称" in a for a in unsupported), "不应把字段名「标题包名称」当 fake 文案"


# ── Finding 1 [P1]：API 契约精确匹配（method+path 完整片段 / payload 字段）──


def test_f1_wrong_api_endpoint_not_main():
    """F1：case 断言 POST /api/accounts/bulk-assign，evidence 只有 POST /api/accounts/list
    （错误 endpoint）→ 不应判 evidence 支撑，应分流 needs_spec。"""
    case = _case(
        "批量分配投放人",
        expected="调用 POST /api/accounts/bulk-assign 接口",
        source_quote="POST /api/accounts/list 查询账户列表",  # 不同 endpoint
    )
    ver = _vc(verdict="grounded", bucket="main")
    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket != "main", "错误 endpoint 不应留 main"


def test_f1_wrong_payload_field_not_main():
    """F1：case 断言 payload 字段 ids/owner，evidence 没写这些字段 → 不应判支撑，分流。"""
    case = _case(
        "批量分配投放人 payload",
        expected="请求体包含字段 ids 和 owner",
        source_quote="批量分配接口接收请求数据",  # 不含 ids/owner
    )
    ver = _vc(verdict="grounded", bucket="main")
    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket != "main", "错误 payload 字段不应留 main"


def test_f1_correct_endpoint_with_evidence_kept_main():
    """F1：case 断言 POST /api/accounts/bulk-assign，evidence 含该完整 endpoint → 保留 main。"""
    case = _case(
        "批量分配投放人",
        expected="调用 POST /api/accounts/bulk-assign 接口",
        source_quote="POST /api/accounts/bulk-assign 批量分配",
    )
    ver = _vc(verdict="grounded", bucket="main")
    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "main", "正确 endpoint 有 evidence 应留 main"


# ── 二审 F1-payload：请求体包含 X 和 Y 句式 ───────────────────────────────


def test_f1_payload_contains_field_form_routed_when_field_missing():
    """二审 F1-payload：assertion=请求体包含 ids 和 owner，evidence=请求体包含 account_id
    （缺 ids/owner）→ 必须分流，不能因"请求体包含"命中就放过。"""
    case = _case(
        "批量分配投放人 payload",
        expected="请求体包含 ids 和 owner",
        source_quote="请求体包含 account_id",  # 不含 ids/owner
    )
    ver = _vc(verdict="grounded", bucket="main")
    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket != "main", "缺字段时不应留 main"


def test_f1_payload_contains_field_form_kept_when_all_fields_present():
    """二审 F1-payload：assertion=请求体包含 ids 和 owner，evidence=请求体包含 ids 和 owner
    （全部字段在）→ 保留 main。"""
    case = _case(
        "批量分配投放人 payload",
        expected="请求体包含 ids 和 owner",
        source_quote="请求体包含 ids 和 owner",
    )
    ver = _vc(verdict="grounded", bucket="main")
    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "main", "全部字段在 evidence 应留 main"


# ── 二审 F1-endpoint：path 精确相等，不允许子串/前缀 ──────────────────────


def test_f1_endpoint_path_not_supported_by_longer_path():
    """二审 F1-endpoint：assertion=POST /api/accounts/list，evidence=POST /api/accounts/listing
    → 不应判支撑（list 是 listing 的前缀，但二者是不同 endpoint），必须分流。"""
    case = _case(
        "查询账户列表",
        expected="调用 POST /api/accounts/list 接口",
        source_quote="POST /api/accounts/listing 分页查询",  # 不同 endpoint
    )
    ver = _vc(verdict="grounded", bucket="main")
    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket != "main", "list 不应被 listing 支撑"


def test_f1_endpoint_exact_match_kept_main():
    """二审 F1-endpoint：assertion 与 evidence 的 method+path 完全相同 → 保留 main。"""
    case = _case(
        "查询账户列表",
        expected="调用 POST /api/accounts/list 接口",
        source_quote="POST /api/accounts/list 查询",
    )
    ver = _vc(verdict="grounded", bucket="main")
    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "main", "完全相同 endpoint 应留 main"


def test_f1_endpoint_embedded_after_chinese_text_detected_as_full_atom():
    """中文动作里紧贴的 POST /api/path 应提取完整 endpoint，不应退化成 POST / /api 碎片。"""
    from src.testcase_generator.stages.verify.guards import _detect_fake_oracles

    atoms = _detect_fake_oracles("点击提交按钮，抓取POST /api/batch/submit请求payload")

    assert "POST /api/batch/submit" in atoms
    assert "POST " not in atoms
    assert "/api/" not in atoms


def test_f1_endpoint_embedded_after_chinese_text_supported_by_evidence_kept_main():
    """中文动作里的 endpoint 与 evidence 完全一致时，不应因 POST / /api 泛片段被误分流。"""
    case = _case(
        "提交批创任务",
        expected="点击提交按钮，抓取POST /api/batch/submit请求payload",
        source_quote="技术方案：提交接口为POST /api/batch/submit。",
    )
    ver = _vc(
        verdict="grounded",
        bucket="main",
        prd_evidence="技术方案：提交接口为POST /api/batch/submit。",
    )

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "main"


# ── 二审 P1：R2 多 atom 漏判（_detect_fake_oracle 只返回首个）──────────────


def test_multi_atom_wrong_endpoint_correct_payload_routed():
    """二审 P1：assertion=POST /api/accounts/bulk-assign + 请求体包含 ids 和 owner，
    evidence=POST /api/accounts/list + 请求体包含 ids 和 owner（payload 支撑但 endpoint 错）。
    当前 _detect_fake_oracle 只返回首个 atom（payload），payload 有支撑就放过 → 漏判 endpoint。
    修复后：检查所有 atom，endpoint 无支撑即分流 needs_spec，unsupported 含错误 endpoint。"""
    case = _case(
        "批量分配投放人",
        expected="POST /api/accounts/bulk-assign 请求体包含 ids 和 owner",
        source_quote="POST /api/accounts/list 请求体包含 ids 和 owner",
    )
    ver = _vc(verdict="grounded", bucket="main")
    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket != "main", "endpoint 错误应分流"
    unsupported = guarded["TC-1"].unsupported_assertions
    assert any("bulk-assign" in a for a in unsupported), "unsupported 应含错误 endpoint"


def test_multi_atom_correct_endpoint_correct_payload_kept_main():
    """二审 P1：assertion 与 evidence 的 endpoint + payload 字段都正确 → 保留 main。"""
    case = _case(
        "批量分配投放人",
        expected="POST /api/accounts/bulk-assign 请求体包含 ids 和 owner",
        source_quote="POST /api/accounts/bulk-assign 请求体包含 ids 和 owner",
    )
    ver = _vc(verdict="grounded", bucket="main")
    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "main", "endpoint + payload 都正确应留 main"


def test_multi_atom_correct_endpoint_wrong_payload_routed():
    """二审 P1：assertion=POST /api/accounts/bulk-assign + 请求体包含 ids 和 owner，
    evidence=POST /api/accounts/bulk-assign + 请求体包含 account_id（endpoint 对但 payload 字段错）。
    修复后：payload atom 无支撑即分流，unsupported 含未支撑字段。"""
    case = _case(
        "批量分配投放人",
        expected="POST /api/accounts/bulk-assign 请求体包含 ids 和 owner",
        source_quote="POST /api/accounts/bulk-assign 请求体包含 account_id",
    )
    ver = _vc(verdict="grounded", bucket="main")
    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket != "main", "payload 字段错误应分流"


def test_multi_atom_payload_field_not_swallow_following_post_path():
    """二审 P1：payload 字段提取不能吞掉后续 POST /path token。
    "请求体包含 ids 和 owner POST /api/accounts/bulk-assign" 里字段应只提 ids/owner，
    不能把 POST 也当字段名。修复后：endpoint atom 仍能被独立检出。"""
    from src.testcase_generator.stages.verify.guards import _detect_fake_oracles

    text = "请求体包含 ids 和 owner POST /api/accounts/bulk-assign"
    atoms = _detect_fake_oracles(text)
    # 应同时检出 payload 字段 atom 和 API method+path atom
    has_payload = any("payload字段" in a for a in atoms)
    has_api = any("POST /api/accounts/bulk-assign" in a for a in atoms)
    assert has_payload, f"应检出 payload 字段 atom，实际 atoms={atoms}"
    assert has_api, f"应检出 API method+path atom，实际 atoms={atoms}"
    # payload 字段 atom 不应含 POST
    payload_atoms = [a for a in atoms if "payload字段" in a]
    assert all("POST" not in a for a in payload_atoms), f"payload atom 吞了 POST：{payload_atoms}"


# ── 三审 P1：payload 字段 evidence 支撑用 substring 致字段误匹配 ──────────


def test_payload_field_id_not_supported_by_user_id():
    """三审 P1：assertion=请求体包含 id，evidence=请求体包含 user_id → id 不应被 user_id 支撑，
    必须分流。当前 substring 匹配 "id" in "user_id" → 误判支撑留 main。"""
    case = _case(
        "接口调用",
        expected="POST /api/a 请求体包含 id",
        source_quote="POST /api/a 请求体包含 user_id",
    )
    ver = _vc(verdict="grounded", bucket="main")
    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket != "main", "id 不应被 user_id 支撑"


def test_payload_field_owner_not_supported_by_owner_id():
    """三审 P1：assertion=请求体包含 owner，evidence=请求体包含 owner_id → owner 不应被 owner_id
    支撑，必须分流。"""
    case = _case(
        "接口调用",
        expected="POST /api/a 请求体包含 owner",
        source_quote="POST /api/a 请求体包含 owner_id",
    )
    ver = _vc(verdict="grounded", bucket="main")
    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket != "main", "owner 不应被 owner_id 支撑"


def test_payload_field_exact_match_kept_main():
    """三审 P1：assertion=请求体包含 ids 和 owner，evidence=请求体包含 ids 和 owner（精确匹配）
    → 保留 main。"""
    case = _case(
        "批量分配",
        expected="POST /api/a 请求体包含 ids 和 owner",
        source_quote="POST /api/a 请求体包含 ids 和 owner",
    )
    ver = _vc(verdict="grounded", bucket="main")
    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "main", "字段精确匹配应留 main"


def test_payload_field_match_order_insensitive():
    """三审 P1：assertion=请求体包含 ids 和 owner，evidence=请求体包含 owner 和 ids（顺序不同）
    → 字段集合相同，保留 main（顺序不敏感）。"""
    case = _case(
        "批量分配",
        expected="POST /api/a 请求体包含 ids 和 owner",
        source_quote="POST /api/a 请求体包含 owner 和 ids",
    )
    ver = _vc(verdict="grounded", bucket="main")
    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "main", "字段集合相同（顺序不同）应留 main"


# ── 四审 P1：payload 多片段收集 + 上下文区分 request/response ──────────────


def test_payload_request_supported_but_response_missing_routed():
    """四审 P1-1：assertion 同时含请求体 ids 和响应体 code，evidence 只有请求体 ids
    （响应体 code 无证据）→ 应分流。当前 _detect_fake_oracles 只取第一段 payload 字段，
    漏掉响应体 code atom。"""
    case = _case(
        "接口调用",
        expected="POST /api/a 请求体包含 ids 响应体包含 code",
        source_quote="POST /api/a 请求体包含 ids",  # 缺响应体 code
    )
    ver = _vc(verdict="grounded", bucket="main")
    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket != "main", "响应体 code 无证据应分流"


def test_payload_response_field_not_supported_by_request_field_routed():
    """四审 P1-2：assertion=响应体包含 code，evidence=请求体包含 code
    → 请求体 code 不能支撑响应体 code（不同上下文），应分流。"""
    case = _case(
        "接口调用",
        expected="POST /api/a 响应体包含 code",
        source_quote="POST /api/a 请求体包含 code",  # 请求体≠响应体
    )
    ver = _vc(verdict="grounded", bucket="main")
    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket != "main", "请求体 code 不能支撑响应体 code"


def test_payload_request_field_not_supported_by_response_field_routed():
    """四审 P1-2 反向：assertion=请求体包含 code，evidence=响应体包含 code
    → 响应体 code 不能支撑请求体 code，应分流。"""
    case = _case(
        "接口调用",
        expected="POST /api/a 请求体包含 code",
        source_quote="POST /api/a 响应体包含 code",  # 响应体≠请求体
    )
    ver = _vc(verdict="grounded", bucket="main")
    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket != "main", "响应体 code 不能支撑请求体 code"


def test_payload_request_and_response_both_supported_kept_main():
    """四审 P1：assertion=请求体包含 ids 响应体包含 code，evidence 同样含两者
    → 请求体 ids 和响应体 code 都有同上下文支撑，保留 main。"""
    case = _case(
        "接口调用",
        expected="POST /api/a 请求体包含 ids 响应体包含 code",
        source_quote="POST /api/a 请求体包含 ids 响应体包含 code",
    )
    ver = _vc(verdict="grounded", bucket="main")
    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "main", "请求体+响应体都有同上下文支撑应留 main"


# ── Finding 3 [P2]：provenance_excerpt 合入 evidence ──────────────────────


def test_f3_provenance_excerpt_supports_oracle_not_degraded():
    """F3：step.source_quote 空、prd_evidence 空，但 provenance_excerpt 支撑具体 oracle 时，
    不应被 R2 误降级。修复前 _merge_evidence 不含 provenance_excerpt → R2 误判无据。"""
    case = VerifyCase(
        case_id="TC-1",
        feature_id="F1",
        title="提交订单失败返回 409",
        steps=[{"action": "提交", "input_data": "", "expected_result": "接口返回 HTTP 409 Conflict"}],
        expected_results=["接口返回 HTTP 409 Conflict"],
        provenance_excerpt="接口返回 HTTP 409 Conflict",  # 溯源摘录支撑，但 step 无 source_quote
    )
    ver = _vc(verdict="grounded", bucket="main", prd_evidence=None)
    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "main", "provenance_excerpt 支撑 oracle 时不应被 R2 误降级"


# ── R3：无技术方案禁写技术派生断言 ────────────────────────────────────────


def test_r3_no_tech_spec_api_contract_routed():
    """无技术方案时，api_contract 维度的接口契约断言不进 main。"""
    case = _case(
        "幂等键防重复提交",
        expected="重复请求返回相同结果，幂等键 X-Idempotency 生效",
        source_quote="支持重复提交不产生重复数据",  # PRD 业务级，无幂等实现
    )
    ver = _vc(verdict="grounded", bucket="main")

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket != "main"


def test_r3_no_tech_spec_worker_cron_routed():
    """无技术方案时，worker/cron/轮询频率断言不进 main。"""
    case = _case(
        "任务每 5 分钟轮询一次",
        expected="后台 worker 每 300 秒拉取一次任务",
        source_quote="系统自动同步任务状态",
    )
    ver = _vc(verdict="grounded", bucket="main")

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket != "main"


def test_r3_prd_explicit_daily_schedule_supports_scheduled_task():
    """PRD 明确每天凌晨遍历/拉取时，定时任务是有据 oracle，不应被 R3 误杀。"""
    case = _case(
        "定时任务每天凌晨执行，遍历所有已授权AD账户拉取素材评估标签",
        expected="定时任务开始执行，逐账户拉取该账户下的全部视频素材评估标签",
        source_quote="每天凌晨遍历所有已授权的巨量广告账户，逐账户拉取该账户下的全部视频素材评估标签。",
    )
    ver = _vc(verdict="grounded", bucket="main")

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "main"
    assert guarded["TC-1"].verdict == "grounded"


def test_r3_auto_sync_without_schedule_does_not_support_scheduled_task():
    """普通自动同步描述不能支撑定时任务/调度机制，仍应进入 needs_spec。"""
    case = _case(
        "定时任务同步任务状态",
        expected="定时任务开始执行并同步任务状态",
        source_quote="系统自动同步任务状态。",
    )
    ver = _vc(verdict="grounded", bucket="main")

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "needs_spec"
    assert guarded["TC-1"].verdict == "undefined"


def test_r3_business_permission_not_killed_without_tech_spec():
    """无技术方案时，PRD 明确的权限/安全/边界业务规则不被误杀。"""
    case = _case(
        "非管理员无权删除订单",
        expected="普通用户点击删除被拒绝",
        source_quote="仅管理员可删除订单",
    )
    ver = _vc(verdict="grounded", bucket="main")

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "main"


def test_r3_business_boundary_not_killed_without_tech_spec():
    """无技术方案时，PRD 明确的字数边界业务规则不被误杀。"""
    case = _case(
        "标题恰好 50 字可保存",
        expected="保存成功",
        source_quote="标题不超过 50 字",
    )
    ver = _vc(verdict="grounded", bucket="main")

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "main"


def test_r3_with_tech_spec_api_contract_kept():
    """有技术方案时，api_contract 断言可进 main。"""
    case = _case(
        "幂等键防重复提交",
        expected="重复请求返回相同结果",
        source_quote="幂等键 X-Idempotency",
    )
    ver = _vc(verdict="grounded", bucket="main")

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs={"TECH §1"})

    assert guarded["TC-1"].bucket == "main"


# ── Finding 2 [P1]：裸「幂等」不应被业务词误放行 ──────────────────────────


def test_f2_bare_idempotence_with_business_words_routed():
    """F2：「保存接口具备幂等能力」，source quote 只有"提交失败后用户可重新提交"
    （含提交/失败/保存业务词）→ 裸幂等是技术实现断言，不应因业务词被业务级放行。应分流。"""
    case = _case(
        "保存接口具备幂等能力",
        expected="重复提交不产生重复数据，接口幂等",
        source_quote="提交失败后用户可重新提交",  # 业务词，但非幂等业务规则
    )
    ver = _vc(verdict="grounded", bucket="main")
    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket != "main", "裸幂等无技术/业务证据不应留 main"


def test_f2_idempotence_with_explicit_business_rule_kept():
    """F2：evidence 明确写出"重复提交不产生重复记录/不会创建重复数据"业务规则时，
    幂等作为业务级断言可保留 main（不误杀真正的幂等业务规则）。"""
    case = _case(
        "重复提交不产生重复订单",
        expected="重复提交不产生重复数据，接口幂等",
        source_quote="重复提交不产生重复记录",  # 明确业务规则
    )
    ver = _vc(verdict="grounded", bucket="main")
    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "main", "明确幂等业务规则应留 main"


# ── R4：cross_section_conflict 分流 ────────────────────────────────────────


def test_r4_cross_section_conflict_routed_to_to_fix_with_evidence():
    """cross_section_conflict=True 且 refs 非空 → 分流到 to_fix，保留冲突证据。"""
    refs = [CrossSectionConflictRef(ref_a="§5.6.1", quote_a="≤50字", ref_b="§9.2", quote_b="不限字数")]
    case = _case("标题包名称恰好50字可保存", expected="保存成功")
    # 当前实现：verdict=grounded + bucket=main + cross_section_conflict=True 会留在 main
    ver = _vc(
        verdict="grounded",
        bucket="main",
        cross_section_conflict=True,
        conflicting_refs=refs,
    )

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    # 不得留在 main
    assert guarded["TC-1"].bucket == "to_fix"
    assert guarded["TC-1"].review_issue_type == "prd_conflict"
    # 冲突证据保留
    assert guarded["TC-1"].cross_section_conflict is True
    assert len(guarded["TC-1"].conflicting_refs) == 1
    assert guarded["TC-1"].conflicting_refs[0].ref_a == "§5.6.1"


def test_r4_cross_section_conflict_no_refs_not_forced_routed():
    """cross_section_conflict=True 但 refs 为空（防御性假信号）→ 不强制改 bucket，
    仍按 verdict 走（避免误伤无证据的假标记）。"""
    case = _case("某用例", expected="某预期")
    ver = _vc(
        verdict="grounded",
        bucket="main",
        cross_section_conflict=True,
        conflicting_refs=[],  # 无 refs
    )

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    # 无 refs 时不强制分流（符合"refs 非空才分流"契约）
    assert guarded["TC-1"].bucket == "main"
    # 且 cross_section_conflict 被修正为 False（无证据的假信号）
    assert guarded["TC-1"].cross_section_conflict is False


def test_r4_task_status_display_name_conflict_demoted_to_needs_spec():
    """任务列表执行状态展示文案 vs 业务状态机状态名不是同层同实体硬冲突。

    当前批次样本：列表执行状态列显示「部分失败」，verify 用业务状态机名
    「提交完成-有失败」反驳并打 to_fix/conflict。正确处理是不把它当 PRD 真冲突执行，
    也不在缺少同层 UI 证据时升回 main，而是降到 needs_spec 待补同层证据。
    """
    case = _case(
        "执行状态取值验证——部分失败状态正确展示",
        expected="任务存在失败子项且有成功子项时，列表执行状态列显示为「部分失败」",
        source_quote="提交完成-有失败 | 至少一个子项 status=failed 且未取消；其余可能成功。",
    )
    ver = CaseVerification(
        verdict="conflict",
        bucket="to_fix",
        rationale="PRD 状态机定义该状态的展示名称为「提交完成-有失败」，用例断言「部分失败」与 PRD 明文不符。",
        prd_evidence="提交完成-有失败 | 至少一个子项 status=failed 且未取消；其余可能成功。",
        conflicting_refs=[],
        cross_section_conflict=False,
        conflict_subject_prd="状态机定义的状态名称",
        conflict_subject_case="任务执行状态列显示文案",
        unsupported_assertions=["执行状态列显示「部分失败」（对应内部状态partial/提交完成-有失败）"],
    )

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "needs_spec"
    assert guarded["TC-1"].verdict == "undefined"
    assert guarded["TC-1"].conflict_entity_mismatch is True
    assert guarded["TC-1"].review_issue_type == "verify_uncertain"
    assert any("状态展示层" in a for a in guarded["TC-1"].unsupported_assertions)


def test_r4_same_layer_task_state_name_conflict_stays_to_fix():
    """真正同层断言业务状态机名称为「部分失败」时，仍保留 to_fix/conflict。"""
    case = _case(
        "任务状态机状态名称应为部分失败",
        expected="任务状态机状态名称显示为「部分失败」",
        source_quote="提交完成-有失败 | 至少一个子项 status=failed 且未取消；其余可能成功。",
    )
    ver = CaseVerification(
        verdict="conflict",
        bucket="to_fix",
        rationale="PRD 状态机定义该状态为「提交完成-有失败」，用例断言「部分失败」与 PRD 明文不符。",
        prd_evidence="提交完成-有失败 | 至少一个子项 status=failed 且未取消；其余可能成功。",
        conflicting_refs=[],
        cross_section_conflict=False,
        conflict_subject_prd="状态机定义的状态名称",
        conflict_subject_case="任务状态机状态名称",
    )

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "to_fix"
    assert guarded["TC-1"].verdict == "conflict"
    assert guarded["TC-1"].conflict_entity_mismatch is False
    assert guarded["TC-1"].review_issue_type == "case_wrong"


def test_r4_geo_ui_selection_limit_not_refuted_by_interface_payload_limit():
    """地理位置 UI 选择上限不应被接口层地区字符串收录上限反驳成硬 conflict。

    当前批次样本：用例断言定向包 UI 中第 1001 个区县起阻止勾选并红框提示，
    verify 拿接口层单次最多收录 200 条地区字符串（超出截断）反驳。二者同为地理位置，
    但一个是 UI 交互选择上限，一个是接口载荷收录上限，不是同层约束。
    """
    case = _case(
        "地理位置-单次最多选1000个区县，超出时阻止并红色提示",
        expected="第1001个区县勾选被阻止，该行红色提示「最多1000个，请精简」",
        source_quote="第 1001 个起阻止勾选 + 红框提示",
    )
    ver = CaseVerification(
        verdict="conflict",
        bucket="to_fix",
        rationale="用例断言地理位置单次最多选 1000 个区县，但 PRD §5.7.1 明确接口层单次最多收录 200 条地区字符串。",
        prd_evidence="§5.7.1 地理位置：接口层单次最多收录 200 条地区字符串（超出截断）。",
        conflicting_refs=[],
        cross_section_conflict=False,
        conflict_subject_prd="地理位置接口层收录上限与截断行为",
        conflict_subject_case="地理位置区县选择上限与超限提示",
        unsupported_assertions=["单次最多选1000个区县", "超出1000时勾选行红色提示并阻止继续勾选"],
        same_entity=True,
    )

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "needs_spec"
    assert guarded["TC-1"].verdict == "undefined"
    assert guarded["TC-1"].conflict_entity_mismatch is True
    assert any("UI" in a and "接口层" in a for a in guarded["TC-1"].unsupported_assertions)


def test_r4_same_layer_geo_interface_limit_conflict_stays_to_fix():
    """真正同层断言接口层可收录 1000 条地区字符串时，仍保留 to_fix/conflict。"""
    case = _case(
        "地理位置接口层支持单次收录1000条地区字符串",
        expected="提交载荷中可一次下发1000条地区字符串，不截断",
        source_quote="接口层单次最多收录 200 条地区字符串（超出截断）。",
    )
    ver = CaseVerification(
        verdict="conflict",
        bucket="to_fix",
        rationale="用例断言接口层可一次收录1000条地区字符串，但 PRD 明确最多200条且超出截断。",
        prd_evidence="接口层单次最多收录 200 条地区字符串（超出截断）。",
        conflicting_refs=[],
        cross_section_conflict=False,
        conflict_subject_prd="地理位置接口层收录上限",
        conflict_subject_case="地理位置接口层收录上限",
        unsupported_assertions=["接口层可一次收录1000条地区字符串"],
        same_entity=True,
    )

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "to_fix"
    assert guarded["TC-1"].verdict == "conflict"
    assert guarded["TC-1"].conflict_entity_mismatch is False


def test_r4_unanchored_numeric_conflict_assertion_demoted_to_needs_spec():
    """verify 不得用 case 中不存在的数字+单位断言制造 hard conflict。

    当前批次样本：case 断言每组配额从 10 改 5 后拆为 200 组，verify 却说
    case 断言「200个创意组均正确包含1个素材」。其中「1个素材」并不存在于 case 断言，
    该 conflict basis 未锚定，不能作为 to_fix/conflict 执行。
    """
    case = _case(
        "每组配额从大改小导致拆分后超过200组时截断并toast",
        expected="系统将每个原有10素材的组拆分为2组（每组5个），100组拆分后应为200组",
        source_quote="每组配额：「每个创意组配置 N 个视频」1–30；从大改小时超额组按新 N 自动拆分。",
    )
    ver = CaseVerification(
        verdict="conflict",
        bucket="to_fix",
        rationale="用例expected_result列表中的一条断言“创建的200个创意组均正确包含1个素材”与PRD拆分规则相悖。",
        prd_evidence="从大改小时超额组按新 N 自动拆分。",
        conflicting_refs=[],
        cross_section_conflict=False,
        conflict_subject_prd="配额修改后每组素材数量",
        conflict_subject_case="配额修改后每组素材数量",
        unsupported_assertions=["创建的200个创意组均正确包含1个素材"],
        same_entity=True,
    )

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "needs_spec"
    assert guarded["TC-1"].verdict == "undefined"
    assert any("未锚定" in a and "1个素材" in a for a in guarded["TC-1"].unsupported_assertions)


def test_r4_anchored_numeric_conflict_assertion_stays_to_fix():
    """case 自己确实断言每组1个素材时，数字+单位已锚定，应保留 hard conflict。"""
    case = _case(
        "每组配额从10改5后错误拆成单素材组",
        expected="拆分后创建200个创意组，每个创意组均包含1个素材",
        source_quote="从大改小时超额组按新 N 自动拆分。",
    )
    ver = CaseVerification(
        verdict="conflict",
        bucket="to_fix",
        rationale="用例断言每组1个素材，但 PRD 要求按新 N=5 自动拆分。",
        prd_evidence="从大改小时超额组按新 N 自动拆分。",
        conflicting_refs=[],
        cross_section_conflict=False,
        conflict_subject_prd="配额修改后每组素材数量",
        conflict_subject_case="配额修改后每组素材数量",
        unsupported_assertions=["创建的200个创意组均正确包含1个素材"],
        same_entity=True,
    )

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "to_fix"
    assert guarded["TC-1"].verdict == "conflict"


def test_r4_delivery_link_empty_state_not_refuted_by_monitoring_link_auto_binding():
    """投放链接空列表 UI 不应被监测链接自动绑定规则反驳成硬 conflict。"""
    case = _case(
        "投放链接过滤结果为空时显示灰色提示并可跳转管理页",
        expected="链接列表为空，显示灰色提示「当前投放方式下没有可用链接」，并提供跳转「投放链接管理」的入口",
        source_quote="投放链接列表，单选；空时灰色提示「当前投放方式下没有可用链接」+ 跳转「投放链接管理」。",
    )
    ver = _vc(
        verdict="conflict",
        bucket="to_fix",
        rationale="用例断言投放链接可能出现空列表，但 PRD §七明确所有广告共用两条预置监测链接，投手无需选择。",
        prd_evidence=(
            "所有广告共用两条预置监测链接（IAA 一条、IAP 一条），"
            "由系统按投放方式自动绑定，投手无需选、无需填、无需关心宏参数。"
        ),
        unsupported_assertions=["链接列表为空，显示灰色提示「当前投放方式下没有可用链接」"],
    )

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "needs_spec"
    assert guarded["TC-1"].verdict == "undefined"
    assert guarded["TC-1"].conflict_entity_mismatch is True
    assert any("投放链接" in a and "监测链接" in a for a in guarded["TC-1"].unsupported_assertions)


def test_r4_same_entity_delivery_link_manual_control_conflict_stays_to_fix():
    """同为投放链接实体时，手动选择控件有无冲突不能被跨实体 guard 降级。"""
    case = _case(
        "投放链接由系统自动推导绑定，投手无需手动选择",
        expected="页面上无投放链接手动选择控件",
        source_quote="投放链接列表，单选；空时灰色提示「当前投放方式下没有可用链接」。",
    )
    ver = _vc(
        verdict="conflict",
        bucket="to_fix",
        rationale="用例断言页面上无投放链接手动选择控件，但 PRD §5.8.3 明确要求存在投放链接列表单选控件。",
        prd_evidence="§5.8.3 投放方式与链接：下半为按当前投放方式自动过滤的投放链接列表，单选。",
        unsupported_assertions=["页面上无投放链接手动选择控件"],
    )

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "to_fix"
    assert guarded["TC-1"].verdict == "conflict"
    assert guarded["TC-1"].conflict_entity_mismatch is False


# ── R5：低信任证据不能单独支撑高精度 oracle ──────────────────────────────


def test_r5_low_trust_alone_cannot_support_precise_oracle():
    """原型/AI caption 单独支撑精确文案/布局断言 → 不进 main。"""
    case = _case(
        "按钮文案为「立即提交」",
        expected="按钮显示「立即提交」四个字",
        source_quote="原型图上按钮写着立即提交",  # 低信任来源
        source_ref="原型 §按钮",
    )
    ver = _vc(verdict="grounded", bucket="main")

    # 传低信任 source_ref（原型），guard 应降权
    guarded = apply_oracle_guards(
        {"TC-1": ver},
        [case],
        tech_source_refs=set(),
        source_trust={"原型 §按钮": 5},  # 5 = 最低信任
    )

    assert guarded["TC-1"].bucket != "main"


def test_r5_high_trust_prd_supports_precise_oracle():
    """PRD 正文支撑的精确文案 → 可进 main。"""
    case = _case(
        "按钮文案为「立即提交」",
        expected="按钮显示「立即提交」",
        source_quote="按钮文案为「立即提交」",
        source_ref="PRD §3.2",
    )
    ver = _vc(verdict="grounded", bucket="main")

    guarded = apply_oracle_guards(
        {"TC-1": ver},
        [case],
        tech_source_refs=set(),
        source_trust={"PRD §3.2": 1},  # 1 = 最高信任
    )

    assert guarded["TC-1"].bucket == "main"


# ── R6：外部目录/"等"不完整时不生成唯一映射断言 ────────────────────────────


def test_r6_external_directory_no_mapping_routed():
    """「见外部目录/等」但无完整映射表时，唯一具体映射断言不进 main。"""
    case = _case(
        "优化目标映射为 active_pay",
        expected="优化目标映射到 active_pay 事件",
        source_quote="优化目标见巨量事件目录",  # 外部目录，无完整映射
    )
    ver = _vc(verdict="grounded", bucket="main")

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket != "main"
    assert any("active_pay" in a for a in guarded["TC-1"].unsupported_assertions)


def test_r6_etc_marker_no_unique_mapping_routed():
    """「等」类省略词 + 唯一具体断言 → 不进 main。"""
    case = _case(
        "状态映射为 PROCESSING",
        expected="状态显示为 PROCESSING",
        source_quote="状态包括待处理、处理中等",  # "等" = 非完整枚举
    )
    ver = _vc(verdict="grounded", bucket="main")

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket != "main"


def test_r6_etc_marker_no_unique_chinese_state_routed():
    """「等」类省略词不能支撑未列明的中文唯一状态名。"""
    case = _case(
        "状态显示为部分失败",
        expected="状态显示为「部分失败」",
        source_quote="状态包括待提交、执行中等",
    )
    ver = _vc(verdict="grounded", bucket="main")

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket != "main"
    assert any("部分失败" in item for item in guarded["TC-1"].unsupported_assertions)


def test_r6_etc_marker_explicitly_listed_chinese_state_keeps_main():
    """证据虽然有「等」，但已直接列明的状态值可支撑对应断言。"""
    case = _case(
        "状态显示为执行中",
        expected="状态显示为「执行中」",
        source_quote="状态包括待提交、执行中等",
    )
    ver = _vc(verdict="grounded", bucket="main")

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "main"


def test_r7_closed_enum_state_value_outside_prd_enum_goes_to_fix():
    """PRD 已给完整状态枚举时，枚举外状态是确定性事实错误。"""
    case = _case(
        "状态显示为部分失败",
        expected="状态显示为「部分失败」",
        source_quote="状态包括待提交、执行中、提交完成-有失败",
    )
    ver = _vc(verdict="grounded", bucket="main")

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "to_fix"
    assert guarded["TC-1"].verdict == "conflict"
    assert guarded["TC-1"].review_issue_type == "case_wrong"
    assert any("部分失败" in item for item in guarded["TC-1"].unsupported_assertions)


def test_r7_closed_enum_state_value_in_prd_enum_keeps_main():
    """完整枚举中已列明的状态值不应被 facts guard 误杀。"""
    case = _case(
        "状态显示为执行中",
        expected="状态显示为「执行中」",
        source_quote="状态包括待提交、执行中、提交完成-有失败",
    )
    ver = _vc(verdict="grounded", bucket="main")

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "main"


# ── R7：字数边界确定性 ────────────────────────────────────────────────────


def test_r7_halfwidth_char_count_9_halfwidth_equals_4_5():
    """9 个半角字符 = 9 * 0.5 = 4.5 半角单位。"""
    assert char_count_halfwidth_units("abcdefghi") == 4.5


def test_r7_round_half_up_4_5_to_5():
    """4.5 按规则向上取整为 5（不是银行家舍入的 4）。"""
    assert round_half_up(4.5) == 5


def test_r7_round_half_up_3_5_to_4():
    """3.5 向上取整为 4。"""
    assert round_half_up(3.5) == 4


def test_r7_mixed_fullwidth_halfwidth():
    """中文(全角=1单位) + 半角(0.5单位) 混合计数。
    2 个中文 + 5 个半角 = 2 + 2.5 = 4.5 → 向上取整 5。"""
    assert char_count_halfwidth_units("中文abcde") == 4.5
    assert round_half_up(char_count_halfwidth_units("中文abcde")) == 5


def test_r7_round_half_up_integer_unchanged():
    """已是整数不变。"""
    assert round_half_up(5.0) == 5
    assert round_half_up(4.0) == 4


def test_r7_high_risk_confidence_note_routed_out_of_main():
    """字数/计数类自检失败说明用例输入与 oracle 不一致，不得留在 main。"""
    case = VerifyCase(
        case_id="TC-1",
        feature_id="F1",
        title="9 个半角字符满足 5 字下限",
        steps=[{"action": "输入", "input_data": "abcdefghi", "expected_result": "保存成功"}],
        expected_results=["保存成功"],
        confidence_note="步骤1字数声明与输入不符：声称9实为5",
    )
    ver = _vc(verdict="grounded", bucket="main")

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "needs_spec"
    assert guarded["TC-1"].verdict == "undefined"
    assert any("字数声明与输入不符" in a for a in guarded["TC-1"].unsupported_assertions)


def test_r7_low_trust_confidence_note_without_self_check_not_routed():
    """普通低信任提示不等于确定性自检失败，不能一刀切移出 main。"""
    case = VerifyCase(
        case_id="TC-1",
        feature_id="F1",
        title="查看按钮",
        steps=[{"action": "查看", "input_data": "", "expected_result": "按钮可见"}],
        expected_results=["按钮可见"],
        confidence_note="来源为 UI 设计稿，建议人工确认交互细节",
    )
    ver = _vc(verdict="grounded", bucket="main")

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "main"


def test_r7_template_char_limit_rejects_halfwidth_200_as_100_chars():
    """模板 100 字符硬上限不能被半角 0.5 字算法放宽成 200 个半角字符。"""
    case = _case(
        "项目名称模板-字数统计遵循半角0.5字规则",
        expected="输入200个半角字母时，字数统计显示100字，未超出上限且可保存",
        source_quote="长度上限每条模板 100 字符（前端 + 服务端校验）。",
    )
    ver = _vc(
        verdict="grounded",
        bucket="main",
        prd_evidence="§5.8.11：长度上限每条模板 100 字符（前端 + 服务端校验）。",
    )

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "to_fix"
    assert guarded["TC-1"].verdict == "conflict"
    assert any("200" in a and "100字符" in a for a in guarded["TC-1"].unsupported_assertions)


def test_r7_template_char_limit_allows_100_halfwidth_chars():
    """模板 100 字符硬上限下，100 个半角字符未超限不应被误杀。"""
    case = _case(
        "项目名称模板-100个半角字符边界",
        expected="输入100个半角字母时未超出100字符上限，可保存",
        source_quote="长度上限每条模板 100 字符（前端 + 服务端校验）。",
    )
    ver = _vc(
        verdict="grounded",
        bucket="main",
        prd_evidence="§5.8.11：长度上限每条模板 100 字符（前端 + 服务端校验）。",
    )

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "main"


def test_r7_title_text_halfwidth_rule_without_template_limit_keeps_main():
    """普通标题文案字数规则没有模板 100 字符证据时，不触发模板硬上限 guard。"""
    case = _case(
        "标题文本半角字数统计",
        expected="输入200个半角字母时，字数统计显示100字",
        source_quote="半角字母、数字、符号按0.5字计算。",
    )
    ver = _vc(
        verdict="grounded",
        bucket="main",
        prd_evidence="半角字母、数字、符号按0.5字计算。",
    )

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "main"


def test_r7_query_param_count_mismatch_in_expected_results_routed():
    """expected_results 中的宏参数数量与 PRD URL query 参数数不一致时，不得留在 main。"""
    prd_url = _url_with_query_param_count(35)
    case = VerifyCase(
        case_id="TC-1",
        feature_id="F1",
        title="验证IAA预置链接宏参数值占位符格式与IAP一致",
        steps=[
            {
                "action": "核对IAA预置链接参数格式",
                "input_data": "",
                "source_quote": f"IAA预置链接：{prd_url}",
                "expected_result": "参数占位符均为双下划线包裹的大写宏名",
            }
        ],
        expected_results=["IAA预置链接中30个宏参数的占位符值格式与IAP链接完全一致，均为双下划线包裹的大写宏名"],
        provenance_excerpt=f"IAA预置链接：{prd_url}",
    )
    ver = _vc(verdict="grounded", bucket="main", prd_evidence=f"IAA预置链接：{prd_url}")

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "needs_spec"
    assert guarded["TC-1"].verdict == "undefined"
    assert any("30" in a and "35" in a for a in guarded["TC-1"].unsupported_assertions)


def test_r7_query_param_count_match_keeps_main():
    """宏参数数量与 PRD URL query 参数数一致时，不应被数量 guard 误杀。"""
    prd_url = _url_with_query_param_count(35)
    case = VerifyCase(
        case_id="TC-1",
        feature_id="F1",
        title="验证IAA预置链接宏参数值占位符格式与IAP一致",
        steps=[
            {
                "action": "核对IAA预置链接参数格式",
                "input_data": "",
                "source_quote": f"IAA预置链接：{prd_url}",
                "expected_result": "参数占位符均为双下划线包裹的大写宏名",
            }
        ],
        expected_results=["IAA预置链接中35个宏参数的占位符值格式与IAP链接完全一致"],
        provenance_excerpt=f"IAA预置链接：{prd_url}",
    )
    ver = _vc(verdict="grounded", bucket="main", prd_evidence=f"IAA预置链接：{prd_url}")

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "main"


def test_r7_query_param_count_claim_without_complete_url_or_count_evidence_routed():
    """证据只有截断 URL 时，不能支撑精确宏参数数量断言。"""
    case = VerifyCase(
        case_id="TC-1",
        feature_id="F1",
        title="验证IAA预置链接仅path部分与IAP不同",
        steps=[
            {
                "action": "对比IAP和IAA两条预置链接的URL结构",
                "input_data": "",
                "source_quote": "IAP：https://example.test/click/a?... IAA：https://example.test/click/b?…",
                "expected_result": "两条链接仅path hash不同，query string参数部分完全一致",
            }
        ],
        expected_results=["query string中的30个宏参数名及占位符值完全一致"],
        provenance_excerpt="IAP：https://example.test/click/a?... IAA：https://example.test/click/b?…",
    )
    ver = _vc(
        verdict="grounded",
        bucket="main",
        prd_evidence="IAP: /click/a?… IAA: /click/b?… 其余部分相同",
    )

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "needs_spec"
    assert any("缺少可核验证据" in a for a in guarded["TC-1"].unsupported_assertions)


def test_r7_query_param_count_claim_supported_by_explicit_evidence_keeps_main():
    """没有完整 URL 但证据明示相同参数数量时，不应被数量 guard 误杀。"""
    case = _case(
        "验证预置链接包含全部30个宏参数",
        expected="预置链接包含全部30个宏参数",
        source_quote="PRD明确：预置链接包含全部30个宏参数",
    )
    ver = _vc(
        verdict="grounded",
        bucket="main",
        prd_evidence="PRD明确：预置链接包含全部30个宏参数",
    )

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert guarded["TC-1"].bucket == "main"


# ── R8：指标不靠删数据美化 ─────────────────────────────────────────────────


def test_r8_ungrounded_not_deleted_but_routed():
    """ungrounded 用例不删除，分流到 needs_spec（风险保留）。"""
    case = _case("凭空断言某接口", expected="返回 code=999")
    ver = _vc(verdict="ungrounded", bucket="needs_spec", unsupported_assertions=["返回 code=999"])

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    # 仍在结果里（没被删），且 bucket=needs_spec
    assert "TC-1" in guarded
    assert guarded["TC-1"].bucket == "needs_spec"
    assert guarded["TC-1"].unsupported_assertions == ["返回 code=999"]


def test_r8_undefined_not_deleted_but_routed():
    """undefined 用例不删除，分流到 needs_spec（风险保留）。"""
    case = _case("二期功能断言", expected="二期支持导出 PDF")
    ver = _vc(verdict="undefined", bucket="needs_spec")

    guarded = apply_oracle_guards({"TC-1": ver}, [case], tech_source_refs=set())

    assert "TC-1" in guarded
    assert guarded["TC-1"].bucket == "needs_spec"


def test_r8_no_case_dropped_from_results():
    """guard 处理前后 case_id 集合不变（不删除任何用例）。"""
    cases = [
        _case("正常用例", expected="正常"),
        _case("待确认用例", expected="需求待确认"),
        _case("凭空用例", expected="返回 code=999"),
    ]
    results = {
        "TC-1": _vc("grounded", "main"),
        "TC-2": _vc("grounded", "main"),
        "TC-3": _vc("ungrounded", "needs_spec"),
    }
    guarded = apply_oracle_guards(results, cases, tech_source_refs=set())
    assert set(guarded.keys()) == {"TC-1", "TC-2", "TC-3"}


# ── 真实接入形状回归（verify_cases 端到端，mock LLM）──────────────────────────
# 审查 P1：原测试直接调 apply_oracle_guards 手工塞参数，绕过了 verify_node 的真实数据流。
# 以下 3 个测试走 verify_cases 全链路（LLM mock → reconcile → guard），锁死真实形状下
# R5 source_ref 透传、R2 兼顾 prd_evidence、R3 不靠全局 has_tech_spec 一刀切放行。


async def test_r5_real_shape_low_trust_source_ref_routed(monkeypatch):
    """真实形状 R5：verify_node 透传 step.source_ref 后，低信任来源支撑精确文案应被降权。

    复现审查 P1-1：若 verify_node 没透传 source_ref，guards 拿到的 src_ref 会退化成
    原文 quote，和 source_trust 的 key 对不上 → R5 失效、bucket 仍 main。
    """
    from src.testcase_generator.stages.verify import verifier as vmod
    from src.testcase_generator.stages.verify.verifier import PrdSection, verify_cases

    # case 的 step 带 source_ref（真实 verify_node 现在透传了）；source_quote 来自原型
    case = VerifyCase(
        case_id="V0",
        feature_id="F1",
        title="按钮文案为立即提交",
        steps=[
            {
                "action": "查看按钮",
                "input_data": "",
                "expected_result": "按钮显示「立即提交」",
                "source_quote": "原型图按钮写着立即提交",
                "source_ref": "原型 §按钮",
            }
        ],
        expected_results=["按钮显示「立即提交」"],
    )

    class _FakeClient:
        async def generate_structured(self, **kw):
            return vmod._VerifyLLMOutput(
                verdicts=[vmod._CaseVerdict(case_id="V0", verdict="grounded", rationale="有支撑")]
            )

    monkeypatch.setattr(vmod, "get_llm_client", lambda: _FakeClient())
    monkeypatch.setattr(vmod.settings, "verdict_reconcile_enabled", False, raising=False)
    monkeypatch.setattr(vmod.settings, "conflict_entity_gate_enabled", False)
    monkeypatch.setattr(vmod.settings, "verify_cross_section_conflict_enabled", False)

    results = await verify_cases(
        [case],
        {"F1": [PrdSection("§3.2", "按钮文案为立即提交", "§3.2")]},
        tech_source_refs=set(),
        source_trust={"原型 §按钮": 5},  # 5 = 最低信任（原型）
    )

    # R5 应生效：低信任来源单独支撑精确文案 → 不进 main
    assert results["V0"].bucket == "needs_spec"
    assert results["V0"].verdict == "ungrounded"
    assert "R5" in results["V0"].rationale


async def test_r2_real_shape_prd_evidence_supports_kept_in_main(monkeypatch):
    """真实形状 R2：生成期 source_quote 缺失，但 verify 找到 prd_evidence 支撑 → 不降级。

    复现审查 P1-2：若 guard 只看 source_quote，verify 已补的 prd_evidence 会被忽略，
    导致后处理覆盖事实核验结果（grounded/main 被误降 needs_spec）。
    """
    from src.testcase_generator.stages.verify import verifier as vmod
    from src.testcase_generator.stages.verify.verifier import PrdSection, verify_cases

    # step 无 source_quote（生成期缺失），但 LLM 在 verify 时找到 prd_evidence
    case = VerifyCase(
        case_id="V0",
        feature_id="F1",
        title="提交订单失败返回 409",
        steps=[
            {
                "action": "提交订单",
                "input_data": "",
                "expected_result": "接口返回 HTTP 409 Conflict",
            }
        ],
        expected_results=["接口返回 HTTP 409 Conflict"],
    )

    class _FakeClient:
        async def generate_structured(self, **kw):
            return vmod._VerifyLLMOutput(
                verdicts=[
                    vmod._CaseVerdict(
                        case_id="V0",
                        verdict="grounded",
                        rationale="PRD 明确 409",
                        prd_evidence="接口返回 HTTP 409 Conflict",
                    )
                ]
            )

    monkeypatch.setattr(vmod, "get_llm_client", lambda: _FakeClient())
    monkeypatch.setattr(vmod.settings, "verdict_reconcile_enabled", False, raising=False)
    monkeypatch.setattr(vmod.settings, "conflict_entity_gate_enabled", False)
    monkeypatch.setattr(vmod.settings, "verify_cross_section_conflict_enabled", False)

    results = await verify_cases(
        [case],
        {"F1": [PrdSection("§5.8", "提交失败返回 HTTP 409", "§5.8")]},
        tech_source_refs=set(),
        source_trust={},
    )

    # R2 不应降级：prd_evidence 已支撑「409」，事实核验结论 grounded/main 保留
    assert results["V0"].bucket == "main"
    assert results["V0"].verdict == "grounded"


async def test_r3_real_shape_tech_spec_present_but_unsupported_worker_routed(monkeypatch):
    """真实形状 R3：batch 含 tech_doc，但当前 case 的 worker 断言未被技术方案支撑 → 仍分流。

    复现审查 P1-3：若用全局 has_tech_spec=True 一刀切放行，无关模块的 worker/cron 断言
    会因 batch 里有任意 tech_doc 而漏进 main。修复后要求技术断言被当前 case 的 evidence
    或对应 tech source_ref 支撑才放行。
    """
    from src.testcase_generator.stages.verify import verifier as vmod
    from src.testcase_generator.stages.verify.verifier import PrdSection, verify_cases

    # case 的 source_ref 是 PRD 章节（非 tech_doc），source_quote 只有业务级描述
    case = VerifyCase(
        case_id="V0",
        feature_id="F1",
        title="任务每 5 分钟轮询一次",
        steps=[
            {
                "action": "等待",
                "input_data": "",
                "expected_result": "后台 worker 每 300 秒拉取一次任务",
                "source_quote": "系统自动同步任务状态",
                "source_ref": "PRD §5.9",
            }
        ],
        expected_results=["后台 worker 每 300 秒拉取一次任务"],
    )

    class _FakeClient:
        async def generate_structured(self, **kw):
            return vmod._VerifyLLMOutput(
                verdicts=[vmod._CaseVerdict(case_id="V0", verdict="grounded", rationale="有支撑")]
            )

    monkeypatch.setattr(vmod, "get_llm_client", lambda: _FakeClient())
    monkeypatch.setattr(vmod.settings, "verdict_reconcile_enabled", False, raising=False)
    monkeypatch.setattr(vmod.settings, "conflict_entity_gate_enabled", False)
    monkeypatch.setattr(vmod.settings, "verify_cross_section_conflict_enabled", False)

    # batch 含 tech_doc（tech_source_refs 非空），但当前 case 的 source_ref 不在其中
    results = await verify_cases(
        [case],
        {"F1": [PrdSection("§5.9", "系统自动同步任务状态", "§5.9")]},
        tech_source_refs={"TECH §异步任务"},  # 技术方案源存在，但与本 case 无关
        source_trust={"PRD §5.9": 1},
    )

    # R3 仍应分流：技术断言「worker/每300秒/每5分钟」未被本 case 的 evidence 或 tech source 支撑
    assert results["V0"].bucket == "needs_spec"
    assert results["V0"].verdict == "undefined"
    assert "R3" in results["V0"].rationale
    assert results["V0"].unsupported_assertions  # 非空：记录被分流的技术断言原文


# ── audit 对抗验证发现的残留漏洞回归 ──────────────────────────────────────────


async def test_r5_multi_step_low_trust_in_non_first_step_routed(monkeypatch):
    """audit P1-1 残留漏洞：多 step 用例，低信任来源支撑的高精度 oracle 在非首 step。

    修复前 _extract_source_ref 只取首个 step.source_ref，R5 仅查首 step trust；首 step 为
    高信任 PRD(trust=1) 时，非首 step 的原型(trust=5)支撑的精确文案漏进 main。
    修复后取所有 step source_ref 中最低信任者判定 → 任一 step 低信任即触发 R5。
    """
    from src.testcase_generator.stages.verify import verifier as vmod
    from src.testcase_generator.stages.verify.verifier import PrdSection, verify_cases

    case = VerifyCase(
        case_id="V0",
        feature_id="F1",
        title="登录后查看按钮",
        steps=[
            {  # step1: 高信任 PRD，无高精度 oracle
                "action": "登录",
                "input_data": "",
                "expected_result": "登录成功",
                "source_ref": "PRD §2.1",
            },
            {  # step2: 低信任原型，高精度 oracle（带引号文案）
                "action": "查看按钮",
                "input_data": "",
                "expected_result": "按钮显示「立即提交」",
                "source_quote": "原型图按钮写着立即提交",
                "source_ref": "原型 §按钮",
            },
        ],
        expected_results=["登录成功", "按钮显示「立即提交」"],
    )

    class _FakeClient:
        async def generate_structured(self, **kw):
            return vmod._VerifyLLMOutput(
                verdicts=[vmod._CaseVerdict(case_id="V0", verdict="grounded", rationale="有支撑")]
            )

    monkeypatch.setattr(vmod, "get_llm_client", lambda: _FakeClient())
    monkeypatch.setattr(vmod.settings, "verdict_reconcile_enabled", False, raising=False)
    monkeypatch.setattr(vmod.settings, "conflict_entity_gate_enabled", False)
    monkeypatch.setattr(vmod.settings, "verify_cross_section_conflict_enabled", False)

    results = await verify_cases(
        [case],
        {"F1": [PrdSection("§2.1", "登录成功", "§2.1")]},
        tech_source_refs=set(),
        source_trust={"PRD §2.1": 1, "原型 §按钮": 5},
    )

    # R5 应生效：非首 step 的低信任来源支撑高精度 oracle → 不进 main
    assert results["V0"].bucket == "needs_spec"
    assert results["V0"].verdict == "ungrounded"
    assert "R5" in results["V0"].rationale


def test_r3_strong_signal_not_preempted_by_generic_retry_plus_business_words():
    """audit P1-3 残留漏洞：强技术信号被泛词「重试」抢占 + 业务词误放行。

    修复前 _detect_tech_derived_assertion 顺序遍历，"重试"(索引靠前) 抢在 "指数退避" 前返回；
    _is_business_level_rule_only 对泛词"重试"再查业务级，文本含"管理员"即放行 → 漏进 main。
    修复后最长匹配返回"指数退避"(强信号)，强信号不算业务级 → 分流。
    """
    case = VerifyCase(
        case_id="V0",
        feature_id="F1",
        title="管理员触发指数退避重试机制",
        steps=[
            {
                "action": "触发",
                "input_data": "",
                "expected_result": "管理员触发指数退避重试机制",
                "source_quote": "仅管理员可操作",
                "source_ref": "PRD §5.9",
            }
        ],
        expected_results=["管理员触发指数退避重试机制"],
    )
    ver = _vc(verdict="grounded", bucket="main", rationale="有支撑")

    guarded = apply_oracle_guards({"V0": ver}, [case], tech_source_refs=set(), source_trust={"PRD §5.9": 1})

    # R3 应分流：强技术信号「指数退避」未被技术方案支撑，不被"重试"泛词+业务词放行
    assert guarded["V0"].bucket == "needs_spec"
    assert guarded["V0"].verdict == "undefined"
    assert "R3" in guarded["V0"].rationale
    assert "指数退避" in guarded["V0"].unsupported_assertions


def test_r3_generic_retry_in_pure_business_context_still_kept():
    """audit P1-3 修复后回归：泛词「重试」在纯业务描述里仍不误杀。

    "失败后可重试提交"——重试是泛词，无强信号，文本是业务级（提交/失败）→ 放行 main。
    确保修复漏洞 2 时没误伤合法的业务级"重试"描述。
    """
    case = VerifyCase(
        case_id="V0",
        feature_id="F1",
        title="提交失败后可重试",
        steps=[
            {
                "action": "提交",
                "input_data": "",
                "expected_result": "失败后可再次提交",
                "source_quote": "提交失败可重试",
                "source_ref": "PRD §5.8",
            }
        ],
        expected_results=["失败后可再次提交"],
    )
    ver = _vc(verdict="grounded", bucket="main", rationale="有支撑")

    guarded = apply_oracle_guards({"V0": ver}, [case], tech_source_refs=set(), source_trust={"PRD §5.8": 1})

    # 泛词"重试"在纯业务级上下文 → 不判技术派生，留 main
    assert guarded["V0"].bucket == "main"


def test_r5_source_ref_normalization_handles_whitespace_and_case():
    """audit 理论风险加固：source_ref 空格/大小写差异不应让 R5 静默失效。

    step.source_ref 是 LLM 生成字段，可能多/少空格或大小写差异；source_trust key 来自
    parsed_context 直取。归一化（strip + 折叠空白 + lower）后匹配，防 R5 失效。
    """
    case = VerifyCase(
        case_id="V0",
        feature_id="F1",
        title="按钮文案",
        steps=[
            {
                "action": "查看",
                "input_data": "",
                "expected_result": "按钮显示「立即提交」",
                "source_quote": "原型按钮写着立即提交",
                "source_ref": "  原型  §按钮  ",  # 前导/中间双/尾随空格
            }
        ],
        expected_results=["按钮显示「立即提交」"],
    )
    ver = _vc(verdict="grounded", bucket="main", rationale="有支撑")

    # source_trust key 无多余空格 → 归一化后应匹配上
    guarded = apply_oracle_guards({"V0": ver}, [case], tech_source_refs=set(), source_trust={"原型 §按钮": 5})

    assert guarded["V0"].bucket == "needs_spec"
    assert "R5" in guarded["V0"].rationale


# ── R4 证据不得被 reconcile_verdicts 抹掉（审查 P1）──────────────────────────


async def test_r4_cross_section_refs_survive_reconcile_then_guard_routes_to_to_fix(monkeypatch):
    """审查 P1：cross_section_conflict=True 且 refs 非空的用例，经 reconcile 后证据必须保留，
    apply_oracle_guards 能据此强制 to_fix。

    复现路径：两条同 feature 高相似用例进 reconcile cluster；C1 是 grounded + cross_section_conflict=True
    + conflicting_refs 非空，C2 是 grounded 无 refs。簇内多数 grounded → reconcile 选 grounded。
    当前 reconcile 在非 conflict 分支无条件清空 cross_section_conflict/conflicting_refs →
    guard 在 reconcile 后执行，看不到 R4 证据 → C1 最终留 main（错误，应 to_fix）。

    修复后：reconcile 不清 cross_section_conflict/conflicting_refs（跨节冲突是 PRD 矛盾事实，
    与用例 verdict 解耦），guard 能看到 refs → C1 强制 to_fix，refs 保留。
    """
    from src.testcase_generator.stages.verify import verifier as vmod
    from src.testcase_generator.stages.verify.verifier import PrdSection, verify_cases

    # 两条同 feature、标题高相似（仅末尾编号不同）→ 满足 reconcile_sim 阈值，进同簇
    cases = [
        VerifyCase(
            case_id="V0",
            feature_id="F1",
            title="标题包名称恰好50字可保存01",
            steps=[{"action": "保存", "input_data": "", "expected_result": "保存成功"}],
            expected_results=["保存成功"],
        ),
        VerifyCase(
            case_id="V1",
            feature_id="F1",
            title="标题包名称恰好50字可保存02",
            steps=[{"action": "保存", "input_data": "", "expected_result": "保存成功"}],
            expected_results=["保存成功"],
        ),
    ]

    class _FakeClient:
        async def generate_structured(self, **kw):
            return vmod._VerifyLLMOutput(
                verdicts=[
                    vmod._CaseVerdict(
                        case_id="V0",
                        verdict="grounded",
                        rationale="有支撑",
                        cross_section_conflict=True,
                        conflicting_refs=[
                            vmod._ConflictRef(ref_a="§5.6.1", quote_a="≤50字", ref_b="§9.2", quote_b="不限字数")
                        ],
                    ),
                    vmod._CaseVerdict(case_id="V1", verdict="grounded", rationale="有支撑"),
                ]
            )

    monkeypatch.setattr(vmod, "get_llm_client", lambda: _FakeClient())
    # 默认 reconcile + guard 都开（真实路径）；关掉其他后处理门控隔离变量
    monkeypatch.setattr(vmod.settings, "verdict_reconcile_enabled", True, raising=False)
    monkeypatch.setattr(vmod.settings, "reconcile_sim", 0.92, raising=False)
    monkeypatch.setattr(vmod.settings, "conflict_entity_gate_enabled", False)
    monkeypatch.setattr(vmod.settings, "verify_cross_section_conflict_enabled", False)

    results = await verify_cases(
        cases,
        {"F1": [PrdSection("§5.6.1", "≤50字", "§5.6.1"), PrdSection("§9.2", "不限字数", "§9.2")]},
        tech_source_refs=set(),
        source_trust={},
    )

    # C1 必须被 R4 强制分流到 to_fix（不能因 reconcile 清了 refs 而留 main）
    assert results["V0"].bucket == "to_fix", "C1 应被 R4 分流到 to_fix，不能留 main"
    # 冲突证据必须保留（不被 reconcile 抹掉，不伪造）
    assert results["V0"].cross_section_conflict is True
    assert len(results["V0"].conflicting_refs) == 1
    assert results["V0"].conflicting_refs[0].ref_a == "§5.6.1"
    # C2 本无 refs，不得被扩散冲突证据
    assert results["V1"].cross_section_conflict is False
    assert results["V1"].conflicting_refs == []
    assert results["V1"].bucket == "main"
