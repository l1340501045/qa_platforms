"""内容注入器 — 把图片描述按归位规则插回 markdown content。

归位策略：
1. md 已引用的图（![]() 中出现的）→ 在 ![]() 行后追加 > [图述] caption_text
2. 未引用的图 → 按 section_hint 编号匹配章节标题，追加到该章节标题下方
3. 匹配不到的 → 归入文末「附：未定位图描述」兜底
"""

from __future__ import annotations

import re

from src.testcase_generator.schemas.image_caption import ImageCaption

_IMAGE_MD_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def inject_captions(content: str, captions: list[ImageCaption]) -> str:
    """将图描述注入 markdown content，返回 enriched content。"""
    if not captions:
        return content

    # 按 filename 索引 captions
    by_filename: dict[str, ImageCaption] = {c.filename: c for c in captions}

    # 1. 处理 md 引用的图：找 ![]() 行，匹配 filename 后追加图述
    lines = content.split("\n")
    injected_filenames: set[str] = set()
    new_lines: list[str] = []

    for line in lines:
        new_lines.append(line)
        m = _IMAGE_MD_RE.search(line)
        if m:
            img_path = m.group(1)
            # 从路径提取文件名
            filename = img_path.rsplit("/", 1)[-1] if "/" in img_path else img_path
            if filename in by_filename:
                cap = by_filename[filename]
                new_lines.append(f"> [图述] {cap.caption_text}")
                injected_filenames.add(filename)

    content = "\n".join(new_lines)

    # 2. 处理未引用的图：按 section_hint 匹配章节
    remaining = [c for c in captions if c.filename not in injected_filenames]
    if not remaining:
        return content

    # 构建章节标题索引：从标题中提取可能的编号
    lines = content.split("\n")
    section_line_map: dict[str, int] = {}
    for i, line in enumerate(lines):
        hm = _HEADING_RE.match(line)
        if hm:
            heading_text = hm.group(2)
            # 从标题中提取 §X.Y.Z 或纯数字编号
            nums = re.findall(r"§?([\dA-Za-z]+(?:\.\d+)*)", heading_text)
            for n in nums:
                section_line_map[n] = i

    placed: list[ImageCaption] = []
    unplaced: list[ImageCaption] = []

    for cap in remaining:
        if cap.section_hint and cap.section_hint in section_line_map:
            placed.append(cap)
        else:
            unplaced.append(cap)

    # 按行号降序插入（避免行号偏移）
    placed_with_line = [
        (section_line_map[cap.section_hint], cap)  # type: ignore[arg-type]
        for cap in placed
    ]
    placed_with_line.sort(key=lambda x: x[0], reverse=True)

    for line_idx, cap in placed_with_line:
        insert_at = line_idx + 1
        # 跳过紧跟标题的空行
        while insert_at < len(lines) and lines[insert_at].strip() == "":
            insert_at += 1
        caption_line = f"> [图述 {cap.filename}] {cap.caption_text}"
        lines.insert(insert_at, caption_line)

    # 3. 无法匹配的归入文末附录
    if unplaced:
        lines.append("")
        lines.append("## 附：未定位图描述")
        lines.append("")
        for cap in unplaced:
            lines.append(f"> [图述 {cap.filename}] {cap.caption_text}")

    return "\n".join(lines)
