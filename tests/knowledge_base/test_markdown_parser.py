"""Markdown canonical snapshot 契约测试。"""

import hashlib

from src.knowledge_base.services.parsers.markdown_parser import (
    MARKDOWN_CANONICAL_IMAGE_ENRICHMENT_REVISION,
    MARKDOWN_CANONICAL_SNAPSHOT_REVISION,
    MarkdownParser,
    canonicalize_markdown,
)


def test_canonical_snapshot_removes_frontmatter_and_strips_body() -> None:
    raw_text = "---\ntitle: 示例 PRD\ntags:\n  - qa\n---\n\n  # 功能说明\n\n正文内容。  \n\n"

    snapshot = canonicalize_markdown(raw_text)

    assert snapshot.revision == MARKDOWN_CANONICAL_SNAPSHOT_REVISION
    assert snapshot.image_enrichment_revision == MARKDOWN_CANONICAL_IMAGE_ENRICHMENT_REVISION
    assert snapshot.content == "# 功能说明\n\n正文内容。"
    assert snapshot.frontmatter == {"title": "示例 PRD", "tags": ["qa"]}
    assert snapshot.canonical_sha256 == hashlib.sha256(snapshot.content.encode("utf-8")).hexdigest()


def test_canonical_snapshot_preserves_markdown_image_references() -> None:
    raw_text = """
![流程图](images/flow.png)

正文 ![界面](./assets/screen.webp)
"""

    snapshot = canonicalize_markdown(raw_text)

    assert snapshot.content == "![流程图](images/flow.png)\n\n正文 ![界面](./assets/screen.webp)"
    assert snapshot.image_refs == ("images/flow.png", "./assets/screen.webp")


def test_markdown_parser_uses_the_same_canonical_snapshot_contract() -> None:
    raw_text = "---\nowner: qa\n---\n\n# 标题\n\n![图](image.png)"

    snapshot = canonicalize_markdown(raw_text)
    parsed = MarkdownParser().parse(raw_text)

    assert parsed.content == snapshot.content
    assert parsed.frontmatter == snapshot.frontmatter
    assert tuple(parsed.image_refs) == snapshot.image_refs
    assert parsed.headings == ["标题"]


def test_canonical_snapshot_ignores_non_mapping_frontmatter() -> None:
    snapshot = canonicalize_markdown("---\n只是一个字符串\n---\n\n# 标题")

    assert snapshot.frontmatter == {}
    assert snapshot.content == "# 标题"
