"""LLMClient 多模态扩展测试：images 参数触发 vision model + multimodal messages"""

import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel, Field

from src.testcase_generator.services.llm_client import LLMClient


class DummyOutput(BaseModel):
    description: str = Field(description="描述")


def _fake_response(content: str):
    """构造 fake OpenAI response"""
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = None
    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = "stop"
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    return resp


class TestVisionMessages:
    """有 images 时构建 multimodal user content + 用 vision model"""

    @pytest.mark.asyncio
    async def test_images_triggers_multimodal_message_format(self):
        """传 images 时 user message 应包含 text + image_url 块"""
        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

        captured_kwargs = {}

        async def capture_create(**kwargs):
            captured_kwargs.update(kwargs)
            return _fake_response(json.dumps({"description": "一个按钮"}))

        with (
            patch("src.testcase_generator.services.llm_client.settings") as mock_settings,
            patch("src.testcase_generator.services.llm_client.AsyncOpenAI") as MockOpenAI,
        ):
            mock_settings.resolved_llm_api_key = "test-key"
            mock_settings.resolved_llm_base_url = "http://test"
            mock_settings.llm_timeout = 60
            mock_settings.llm_primary_model = "primary-model"
            mock_settings.llm_vision_model = "claude-opus-4-6"
            mock_settings.llm_max_retries = 1
            mock_settings.llm_json_mode = False

            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(side_effect=capture_create)
            MockOpenAI.return_value = mock_client

            client = LLMClient()
            result = await client.generate_structured(
                system_prompt="描述这张图",
                user_content="请描述图片内容",
                output_schema=DummyOutput,
                images=[fake_png],
            )

        assert result.description == "一个按钮"

        # 验证用了 vision model
        assert captured_kwargs["model"] == "claude-opus-4-6"

        # 验证 user message 是 multimodal 结构
        messages = captured_kwargs["messages"]
        user_msg = messages[1]
        assert user_msg["role"] == "user"
        assert isinstance(user_msg["content"], list)

        content_types = [block["type"] for block in user_msg["content"]]
        assert "text" in content_types
        assert "image_url" in content_types

        # 验证 image base64 编码正确
        img_block = next(b for b in user_msg["content"] if b["type"] == "image_url")
        expected_b64 = base64.b64encode(fake_png).decode()
        assert f"data:image/png;base64,{expected_b64}" == img_block["image_url"]["url"]

    @pytest.mark.asyncio
    async def test_no_images_uses_primary_model_text_only(self):
        """不传 images 时走原纯文本路径 + primary model"""
        captured_kwargs = {}

        async def capture_create(**kwargs):
            captured_kwargs.update(kwargs)
            return _fake_response(json.dumps({"description": "纯文本结果"}))

        with (
            patch("src.testcase_generator.services.llm_client.settings") as mock_settings,
            patch("src.testcase_generator.services.llm_client.AsyncOpenAI") as MockOpenAI,
        ):
            mock_settings.resolved_llm_api_key = "test-key"
            mock_settings.resolved_llm_base_url = "http://test"
            mock_settings.llm_timeout = 60
            mock_settings.llm_primary_model = "primary-model"
            mock_settings.llm_vision_model = "claude-opus-4-6"
            mock_settings.llm_max_retries = 1
            mock_settings.llm_json_mode = False

            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(side_effect=capture_create)
            MockOpenAI.return_value = mock_client

            client = LLMClient()
            result = await client.generate_structured(
                system_prompt="测试",
                user_content="纯文本问题",
                output_schema=DummyOutput,
            )

        assert result.description == "纯文本结果"
        assert captured_kwargs["model"] == "primary-model"

        # user message 应为纯字符串
        user_msg = captured_kwargs["messages"][1]
        assert isinstance(user_msg["content"], str)

    @pytest.mark.asyncio
    async def test_vision_model_not_configured_raises_clear_error(self):
        """llm_vision_model 未配置时传 images 应抛清晰错误"""
        with (
            patch("src.testcase_generator.services.llm_client.settings") as mock_settings,
            patch("src.testcase_generator.services.llm_client.AsyncOpenAI"),
        ):
            mock_settings.resolved_llm_api_key = "test-key"
            mock_settings.resolved_llm_base_url = "http://test"
            mock_settings.llm_timeout = 60
            mock_settings.llm_primary_model = "primary-model"
            mock_settings.llm_vision_model = ""  # 未配置
            mock_settings.llm_max_retries = 1
            mock_settings.llm_json_mode = False

            client = LLMClient()
            with pytest.raises(ValueError, match="LLM_VISION_MODEL"):
                await client.generate_structured(
                    system_prompt="描述",
                    user_content="文本",
                    output_schema=DummyOutput,
                    images=[b"fake"],
                )

    @pytest.mark.asyncio
    async def test_multiple_images_all_included(self):
        """多张图都应被编码进 messages"""
        img1 = b"\x89PNG" + b"\x01" * 50
        img2 = b"\x89PNG" + b"\x02" * 50

        captured_kwargs = {}

        async def capture_create(**kwargs):
            captured_kwargs.update(kwargs)
            return _fake_response(json.dumps({"description": "两张图"}))

        with (
            patch("src.testcase_generator.services.llm_client.settings") as mock_settings,
            patch("src.testcase_generator.services.llm_client.AsyncOpenAI") as MockOpenAI,
        ):
            mock_settings.resolved_llm_api_key = "test-key"
            mock_settings.resolved_llm_base_url = "http://test"
            mock_settings.llm_timeout = 60
            mock_settings.llm_primary_model = "primary-model"
            mock_settings.llm_vision_model = "claude-opus-4-6"
            mock_settings.llm_max_retries = 1
            mock_settings.llm_json_mode = False

            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(side_effect=capture_create)
            MockOpenAI.return_value = mock_client

            client = LLMClient()
            await client.generate_structured(
                system_prompt="描述",
                user_content="请描述",
                output_schema=DummyOutput,
                images=[img1, img2],
            )

        user_content = captured_kwargs["messages"][1]["content"]
        image_blocks = [b for b in user_content if b["type"] == "image_url"]
        assert len(image_blocks) == 2
