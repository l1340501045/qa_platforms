"""Markdown 解析器 — 提取正文、图片链接、frontmatter"""

import hashlib
import re
from dataclasses import dataclass, field

import yaml  # type: ignore[import-untyped]

MARKDOWN_CANONICAL_SNAPSHOT_REVISION = "markdown-canonical-v1"
MARKDOWN_CANONICAL_IMAGE_ENRICHMENT_REVISION = "image-enrichment-none-v1"


@dataclass(frozen=True)
class CanonicalMarkdownSnapshot:
    """Markdown 原文的确定性快照，不包含图片描述等外部增强。"""

    revision: str
    image_enrichment_revision: str
    content: str
    canonical_sha256: str
    frontmatter: dict[str, object]
    image_refs: tuple[str, ...]
    headings: tuple[str, ...]


@dataclass
class ParsedDocument:
    """解析后的文档结构"""

    content: str = ""
    image_refs: list[str] = field(default_factory=list)
    frontmatter: dict[str, object] = field(default_factory=dict)
    headings: list[str] = field(default_factory=list)


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def canonicalize_markdown(raw_text: str) -> CanonicalMarkdownSnapshot:
    """把 Markdown 原文转换为版本化、可复现的纯文本快照。

    该函数只处理 Markdown 本身，不读取文件，也不执行图片描述或其他 LLM 增强。
    """
    frontmatter: dict[str, object] = {}
    body = raw_text
    fm_match = _FRONTMATTER_RE.match(raw_text)
    if fm_match:
        try:
            loaded_frontmatter: object = yaml.safe_load(fm_match.group(1))
            if isinstance(loaded_frontmatter, dict):
                frontmatter = {str(key): value for key, value in loaded_frontmatter.items()}
        except yaml.YAMLError:
            frontmatter = {}
        body = raw_text[fm_match.end() :]

    content = body.strip()
    image_refs = tuple(match.group(2) for match in _IMAGE_RE.finditer(body))
    headings = tuple(match.group(2).strip() for match in _HEADING_RE.finditer(body))

    return CanonicalMarkdownSnapshot(
        revision=MARKDOWN_CANONICAL_SNAPSHOT_REVISION,
        image_enrichment_revision=MARKDOWN_CANONICAL_IMAGE_ENRICHMENT_REVISION,
        content=content,
        canonical_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        frontmatter=frontmatter,
        image_refs=image_refs,
        headings=headings,
    )


class MarkdownParser:
    """Markdown 文件解析"""

    def parse(self, raw_text: str) -> ParsedDocument:
        """解析原始 markdown 文本"""
        snapshot = canonicalize_markdown(raw_text)
        return ParsedDocument(
            content=snapshot.content,
            image_refs=list(snapshot.image_refs),
            frontmatter=snapshot.frontmatter,
            headings=list(snapshot.headings),
        )
