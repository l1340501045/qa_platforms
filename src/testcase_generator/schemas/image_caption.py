"""图片描述 schema — 视觉 LLM 输出结构"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ImageCaption(BaseModel):
    """单张图片的结构化描述"""

    filename: str = Field(description="图片文件名")
    section_hint: str | None = Field(default=None, description="章节编号提示（来自文件名）")
    kind: Literal["screen", "flow", "statemachine", "config"] = Field(
        description="图片类型：界面截图/流程图/状态机/配置图"
    )
    ui_elements: list[str] = Field(default_factory=list, description="识别到的 UI 元素（按钮/弹窗/分页等）")
    flow_steps: list[str] = Field(default_factory=list, description="流程步骤（flow/statemachine 类有值）")
    caption_text: str = Field(description="可被测试用例引用的事实性文字描述")
