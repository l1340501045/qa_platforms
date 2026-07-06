"""用例级优先级校准。

TestPoint 的优先级表达“这个测试点为什么重要”；单条 case 还要看它实际断言的
业务后果。纯展示/存在性核对不应因为父测试点是 P0 就占用 P0 执行预算。
"""

from __future__ import annotations

import re

DISPLAY_OR_EXISTENCE_RE = re.compile(
    r"入口|页面|预览|展示|显示|可见|按钮|Tab|字段|列表|表格|弹窗|文案|"
    r"占位|默认|筛选项|表头|回显|展开|收起|折叠|提示|图标|排序|分页|hover|卡片"
)
BUSINESS_RISK_RE = re.compile(
    r"提交|创建|保存|删除|解绑|校验|阻止|失败|写入|生成|拆包|分配|算法|候选池|循环复用|"
    r"限流|权限|拦截|错误|导入|上传|同步|拉取|重试|超时|幂等|锁|任务|"
    r"接口|payload|worker|ack|恢复|预算|出价|替换|"
    r"通配符|清空|保留|不可|适用|范围|上限|下限|必填|为空|超过|边界|"
    r"格式|参数|枚举|缺失|失效|绑定|宏|频控|串行|并发"
)
STRUCTURAL_SIGNAL_DIMENSIONS = {
    "access_control",
    "api_contract",
    "concurrency_state",
    "cross_system",
    "data_integrity",
    "idempotency",
    "recovery",
    "state_transition",
}
STRUCTURAL_SIGNAL_RE = re.compile(
    r"权限|状态机|角色|数据权限|防超限|提交底层|事件资产|监测链接|任务中心|worker|幂等|锁"
)


def case_priority_text(
    *,
    title: str,
    expected_results: list[str] | tuple[str, ...],
    step_expected_results: list[str] | tuple[str, ...],
) -> str:
    """拼接参与优先级校准的可观察断言文本。"""
    return " ".join(
        [title or ""]
        + [str(item or "") for item in expected_results]
        + [str(item or "") for item in step_expected_results]
    )


def has_display_or_existence_signal(text: str) -> bool:
    return bool(DISPLAY_OR_EXISTENCE_RE.search(text or ""))


def has_business_risk_signal(text: str) -> bool:
    return bool(BUSINESS_RISK_RE.search(text or ""))


def has_structural_signal(dimensions: list[str] | tuple[str, ...], text: str) -> bool:
    dim_set = {str(dim or "").strip() for dim in dimensions}
    return bool(dim_set & STRUCTURAL_SIGNAL_DIMENSIONS) or bool(STRUCTURAL_SIGNAL_RE.search(text or ""))


def is_low_value_display_case(
    *,
    title: str,
    expected_results: list[str] | tuple[str, ...],
    step_expected_results: list[str] | tuple[str, ...],
    dimensions: list[str] | tuple[str, ...],
) -> bool:
    """是否为低价值展示/存在性 case。

    判定故意偏保守：只有展示信号存在，且没有业务风险、结构化覆盖信号时才命中。
    """
    text = case_priority_text(
        title=title,
        expected_results=expected_results,
        step_expected_results=step_expected_results,
    )
    return (
        has_display_or_existence_signal(text)
        and not has_business_risk_signal(text)
        and not has_structural_signal(dimensions, text)
    )


def calibrate_case_priority(
    *,
    parent_priority: str,
    title: str,
    expected_results: list[str] | tuple[str, ...],
    step_expected_results: list[str] | tuple[str, ...],
    dimensions: list[str] | tuple[str, ...],
) -> str:
    """根据单条 case 的真实断言校准优先级。

    当前只做 P0 降噪：低价值展示/存在性 case 从 P0 降为 P2；其它优先级和高风险
    P0 保持不变，避免误伤主链路、权限、状态、数据完整性等覆盖。
    """
    if parent_priority != "P0":
        return parent_priority
    if is_low_value_display_case(
        title=title,
        expected_results=expected_results,
        step_expected_results=step_expected_results,
        dimensions=dimensions,
    ):
        return "P2"
    return parent_priority
