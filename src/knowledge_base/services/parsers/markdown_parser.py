"""Markdown 解析器 — 提取正文、图片链接、frontmatter"""

import re
from dataclasses import dataclass, field

import yaml


@dataclass
class ParsedDocument:
    """解析后的文档结构"""

    content: str = ""
    image_refs: list[str] = field(default_factory=list)
    frontmatter: dict = field(default_factory=dict)
    headings: list[str] = field(default_factory=list)


class MarkdownParser:
    """Markdown 文件解析"""

    # 匹配 frontmatter 块 (---\n...\n---)
    _FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
    # 匹配 markdown 图片 ![alt](url)
    _IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
    # 匹配 heading
    _HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

    def parse(self, raw_text: str) -> ParsedDocument:
        """解析原始 markdown 文本"""
        result = ParsedDocument()

        # 提取 frontmatter
        fm_match = self._FRONTMATTER_RE.match(raw_text)
        body = raw_text
        if fm_match:
            try:
                result.frontmatter = yaml.safe_load(fm_match.group(1)) or {}
            except yaml.YAMLError:
                result.frontmatter = {}
            body = raw_text[fm_match.end() :]

        # 提取图片链接
        result.image_refs = [m.group(2) for m in self._IMAGE_RE.finditer(body)]

        # 提取标题
        result.headings = [m.group(2).strip() for m in self._HEADING_RE.finditer(body)]

        # 正文（去除 frontmatter 后的全文）
        result.content = body.strip()

        return result
