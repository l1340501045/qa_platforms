"""内容注入器测试：图描述按归位规则插回 markdown content"""

import pytest

from src.knowledge_base.services.image_caption.content_injector import inject_captions
from src.testcase_generator.schemas.image_caption import ImageCaption


def _caption(filename: str, hint: str | None, text: str, referenced: bool = False) -> ImageCaption:
    return ImageCaption(
        filename=filename,
        section_hint=hint,
        kind="screen",
        ui_elements=[],
        flow_steps=[],
        caption_text=text,
    )


class TestInjectCaptions:
    def test_referenced_image_appended_after_markdown_ref(self):
        """md 引用的图：在 ![]() 后追加 > [图述] caption"""
        content = "# 第一章\n\n一些文字\n\n![图1](images/img-01.png)\n\n后续文字"
        captions = [_caption("img-01.png", "01", "登录页面含用户名密码输入框", referenced=True)]

        result = inject_captions(content, captions)

        assert "![图1](images/img-01.png)" in result
        assert "> [图述] 登录页面含用户名密码输入框" in result
        # 图述应紧跟在 ![]() 之后
        lines = result.split("\n")
        img_idx = next(i for i, l in enumerate(lines) if "![图1]" in l)
        assert "> [图述]" in lines[img_idx + 1]

    def test_unreferenced_image_placed_by_section_hint(self):
        """未引用的图：按 section_hint 匹配章节标题下追加"""
        content = "# §5.8 投放方式\n\n投放方式说明\n\n## §5.8.3 定向投放\n\n定向投放详情"
        captions = [_caption("prd-5.8.3-detail.png", "5.8.3", "定向投放配置弹窗")]

        result = inject_captions(content, captions)

        assert "> [图述 prd-5.8.3-detail.png] 定向投放配置弹窗" in result
        # 应在 §5.8.3 章节下
        lines = result.split("\n")
        section_idx = next(i for i, l in enumerate(lines) if "§5.8.3" in l)
        caption_idx = next(i for i, l in enumerate(lines) if "prd-5.8.3-detail.png" in l)
        assert caption_idx > section_idx

    def test_unmatched_hint_goes_to_appendix(self):
        """匹配不到章节的图归入文末附录"""
        content = "# §1 概述\n\n简介"
        captions = [_caption("prd-99-unknown.png", "99", "未知章节的截图")]

        result = inject_captions(content, captions)

        assert "未定位图描述" in result
        assert "> [图述 prd-99-unknown.png] 未知章节的截图" in result

    def test_mixed_referenced_and_unreferenced(self):
        """混合场景：引用图 + 未引用图 + 无法匹配图"""
        content = (
            "# §5.0 全局\n\n全局说明\n\n"
            "![流程图](images/prd-F1-flow.png)\n\n"
            "## §5.7 定向包\n\n定向包说明"
        )
        captions = [
            _caption("prd-F1-flow.png", "F1", "授权流程图含3步骤", referenced=True),
            _caption("prd-5.7-detail.png", "5.7", "定向包编辑界面"),
            _caption("prd-99-orphan.png", "99", "孤儿图"),
        ]

        result = inject_captions(content, captions)

        # 引用图：紧跟 ![]() 后
        assert "> [图述] 授权流程图含3步骤" in result
        # 未引用图：在 §5.7 章节下
        assert "> [图述 prd-5.7-detail.png] 定向包编辑界面" in result
        # 无法匹配：在附录
        assert "> [图述 prd-99-orphan.png] 孤儿图" in result

    def test_no_captions_returns_unchanged(self):
        """无 caption → content 不变"""
        content = "# Hello\n\nWorld"
        result = inject_captions(content, [])
        assert result == content
