"""视觉描述生成器测试：并发描述 + 失败隔离"""

import pytest

from src.knowledge_base.services.image_caption.caption_service import caption_images
from src.knowledge_base.services.image_caption.image_collector import ImageRef
from src.testcase_generator.schemas.image_caption import ImageCaption


def _img_ref(filename: str, hint: str | None = None) -> ImageRef:
    return ImageRef(
        object_key=f"systems/x/documents/images/{filename}",
        filename=filename,
        referenced_in_md=False,
        section_hint=hint,
    )


class TestCaptionImages:
    @pytest.mark.asyncio
    async def test_basic_caption_generation(self):
        """正常路径：fake client 返回结构化 caption"""
        images = [_img_ref("prd-80-batch.png", "80")]
        image_bytes = {images[0].object_key: b"\x89PNG\x00" * 10}

        async def fake_generate(*, system_prompt, user_content, output_schema, images: list[bytes] | None = None, **kw):
            return ImageCaption(
                filename="prd-80-batch.png",
                section_hint="80",
                kind="screen",
                ui_elements=["创建按钮", "分页器"],
                flow_steps=[],
                caption_text="批量创建页面，含创建按钮和底部分页器",
            )

        result = await caption_images(
            image_refs=images,
            image_bytes_map=image_bytes,
            generate_fn=fake_generate,
            concurrency=2,
        )

        assert len(result) == 1
        assert isinstance(result[0], ImageCaption)
        assert result[0].filename == "prd-80-batch.png"
        assert result[0].kind == "screen"
        assert "创建按钮" in result[0].ui_elements

    @pytest.mark.asyncio
    async def test_failure_isolation(self):
        """单图失败不影响其余图"""
        images = [
            _img_ref("img-01.png", "01"),
            _img_ref("img-02.png", "02"),
            _img_ref("img-03.png", "03"),
        ]
        image_bytes = {img.object_key: b"\x89PNG" for img in images}

        call_count = {"n": 0}

        async def flaky_generate(*, system_prompt, user_content, output_schema, images: list[bytes] | None = None, **kw):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("vision 模型超时")
            return ImageCaption(
                filename=f"img-{call_count['n']:02d}.png",
                section_hint=None,
                kind="screen",
                ui_elements=[],
                flow_steps=[],
                caption_text=f"描述{call_count['n']}",
            )

        result = await caption_images(
            image_refs=images,
            image_bytes_map=image_bytes,
            generate_fn=flaky_generate,
            concurrency=1,
        )

        # 第 2 张失败，只得到 2 个结果
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_concurrency_respected(self):
        """并发度控制"""
        images = [_img_ref(f"img-{i}.png", str(i)) for i in range(6)]
        image_bytes = {img.object_key: b"\x89PNG" for img in images}

        import asyncio
        max_concurrent = {"val": 0, "current": 0}

        async def counting_generate(*, system_prompt, user_content, output_schema, images: list[bytes] | None = None, **kw):
            max_concurrent["current"] += 1
            max_concurrent["val"] = max(max_concurrent["val"], max_concurrent["current"])
            await asyncio.sleep(0.01)
            max_concurrent["current"] -= 1
            return ImageCaption(
                filename="x.png", section_hint=None, kind="screen",
                ui_elements=[], flow_steps=[], caption_text="x",
            )

        await caption_images(
            image_refs=images,
            image_bytes_map=image_bytes,
            generate_fn=counting_generate,
            concurrency=3,
        )

        assert max_concurrent["val"] <= 3

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty(self):
        """空输入 → 空结果"""
        result = await caption_images(
            image_refs=[],
            image_bytes_map={},
            generate_fn=None,  # type: ignore
            concurrency=2,
        )
        assert result == []
