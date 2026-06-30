"""图归位语义匹配单测。"""

from __future__ import annotations

from src.knowledge_base.services.image_caption.content_injector import inject_captions
from src.testcase_generator.schemas.image_caption import ImageCaption


def test_semantic_relocation_when_number_mismatch():
    """section_hint 编号对不上，但 caption 含章节名 → 应归位该章节而非附录"""
    content = "# 文档\n\n## 5.2 漫剧库\n\n正文。\n\n## 5.9 任务中心\n\n正文。\n"
    cap = ImageCaption(
        filename="x-20-dramas.png",
        kind="screen",
        caption_text="漫剧库列表页面，展示漫剧 id/名称",
        section_hint="20",
    )
    out = inject_captions(content, [cap])
    assert "附：未定位图描述" not in out
    lines = out.split("\n")
    drama_idx = next(i for i, line in enumerate(lines) if "5.2 漫剧库" in line)
    assert any("漫剧库列表页面" in line for line in lines[drama_idx : drama_idx + 4])


def test_number_match_still_works():
    """编号匹配正常命中时仍走编号路径"""
    content = "# 文档\n\n## 5.2 漫剧库\n\n正文。\n"
    cap = ImageCaption(
        filename="img-5.2-demo.png",
        kind="screen",
        caption_text="某截图",
        section_hint="5.2",
    )
    out = inject_captions(content, [cap])
    assert "附：未定位图描述" not in out
    lines = out.split("\n")
    drama_idx = next(i for i, line in enumerate(lines) if "5.2 漫剧库" in line)
    assert any("某截图" in line for line in lines[drama_idx : drama_idx + 4])


def test_no_match_goes_to_appendix():
    """编号和语义都不匹配时仍进附录"""
    content = "# 文档\n\n## 5.2 漫剧库\n\n正文。\n"
    cap = ImageCaption(
        filename="random-99.png",
        kind="flow",
        caption_text="完全不相关的内容",
        section_hint="99",
    )
    out = inject_captions(content, [cap])
    assert "附：未定位图描述" in out


def test_semantic_relocation_preserves_internal_digits():
    """标题正文含数字（双11）时不应被去编号正则误删为"双" → 仍能语义命中归位。"""
    content = "# 文档\n\n## 5.3 双11活动页\n\n正文。\n"
    cap = ImageCaption(
        filename="x.png",
        kind="screen",
        caption_text="双11活动页的横幅展示",
        section_hint="88",  # 编号对不上，强制走语义匹配
    )
    out = inject_captions(content, [cap])
    assert "附：未定位图描述" not in out
    lines = out.split("\n")
    idx = next(i for i, line in enumerate(lines) if "5.3 双11活动页" in line)
    assert any("双11活动页的横幅展示" in line for line in lines[idx + 1 : idx + 4])
