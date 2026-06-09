"""T022: Gate NO_GO 挂起处理 — 使用 LangGraph 原生 interrupt()"""

from __future__ import annotations

from langgraph.types import interrupt

from src.testcase_generator.schemas.comprehension_report import OpenQuestion


def handle_gate_no_go(open_questions: list[OpenQuestion]) -> dict:
    """NO_GO 时调用 interrupt() 挂起流水线等待人工输入

    使用 LangGraph 原生 interrupt()（硬约束#2），不是 END+重新 invoke。
    挂起后 state.status → suspended，open_questions 写入 stage_artifacts。
    恢复时用 Command(resume={"clarification_answers": [...]})。

    Args:
        open_questions: 需要用户回答的问题列表

    Returns:
        用户恢复后通过 Command(resume=...) 传入的回答数据
    """
    # 构造需要用户回答的问题列表
    questions_for_user = [
        {
            "question_id": q.question_id,
            "question": q.question,
            "context": q.context,
            "related_features": q.related_features,
            "blocking": q.blocking,
        }
        for q in open_questions
    ]

    # LangGraph 原生挂起 — 流水线在此暂停
    # 用户回答后通过 Command(resume={"clarification_answers": [...]}) 恢复
    # interrupt() 返回值即为 resume 传入的数据
    user_response = interrupt(questions_for_user)

    return user_response
