"""视觉描述生成器 — 并发调 vision LLM 描述每张图，失败隔离。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine

from src.knowledge_base.services.image_caption.image_collector import ImageRef
from src.testcase_generator.schemas.image_caption import ImageCaption

logger = logging.getLogger(__name__)

VISION_SYSTEM_PROMPT = """你是专业 QA 图片分析师。请分析这张产品截图/流程图/状态机图，输出结构化描述。

规则：
- kind 判断：界面截图=screen，流程图=flow，状态机图=statemachine，配置/参数图=config
- ui_elements：识别按钮、弹窗、分页器、输入框、下拉框、开关、标签页等 UI 控件（screen 类必填）
- flow_steps：流程步骤或状态节点与转移（flow/statemachine 类必填）
- caption_text：一段可被测试用例引用的事实性描述，不臆造 PRD 未展示的功能
- 只描述图中可见的事实，不推测图外逻辑"""


async def caption_images(
    *,
    image_refs: list[ImageRef],
    image_bytes_map: dict[str, bytes],
    generate_fn: Callable[..., Coroutine[Any, Any, ImageCaption]],
    concurrency: int = 4,
) -> list[ImageCaption]:
    """并发描述图片列表，失败隔离（单图失败不影响其余）。

    Args:
        image_refs: 图片引用列表（来自 collect_images）
        image_bytes_map: object_key → 图片字节的映射
        generate_fn: 视觉 LLM 调用函数（签名兼容 LLMClient.generate_structured）
        concurrency: 并发度

    Returns:
        成功描述的 ImageCaption 列表（失败的被跳过）
    """
    if not image_refs:
        return []

    semaphore = asyncio.Semaphore(concurrency)
    results: list[ImageCaption | None] = [None] * len(image_refs)

    async def _describe_one(idx: int, ref: ImageRef) -> None:
        async with semaphore:
            img_bytes = image_bytes_map.get(ref.object_key)
            if not img_bytes:
                logger.warning("图片字节缺失，跳过: %s", ref.object_key)
                return

            user_text = f"请分析图片: {ref.filename}"
            if ref.section_hint:
                user_text += f"（对应章节编号: {ref.section_hint}）"

            try:
                caption = await generate_fn(
                    system_prompt=VISION_SYSTEM_PROMPT,
                    user_content=user_text,
                    output_schema=ImageCaption,
                    images=[img_bytes],
                )
                caption.filename = ref.filename
                caption.section_hint = ref.section_hint
                results[idx] = caption
            except Exception as e:  # noqa: BLE001
                logger.error("图片描述失败 %s: %s", ref.filename, e)

    await asyncio.gather(*[_describe_one(i, ref) for i, ref in enumerate(image_refs)])

    return [r for r in results if r is not None]
