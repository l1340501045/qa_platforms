"""回归测试：parse 按"功能模块"粒度聚合标题，丢弃非功能元信息段。

根因背景：原实现把每个 markdown 标题（含 4 级细节、变更日志/背景等元信息）
都当成一个功能点，真实 PRD 切出 127 个碎片 →（1）同一功能上下文被切散，
AI 理解不准、用例质量下降；（2）对"变更日志"等非功能段生成无意义用例。
聚合后：以二级标题为模块粒度、深层折叠进父模块、元信息整树丢弃。
"""

from uuid import uuid4

from src.knowledge_base.schemas.common import SearchResult
from src.testcase_generator.stages.parse.node import (
    _extract_sections,
    extract_document_inventory_sections,
    extract_document_sections,
    extract_seed_document_sections,
)


def _result(md: str) -> SearchResult:
    return SearchResult(
        document_id=uuid4(),
        title="PRD",
        content_snippet=md,
        score=1.0,
        source="seed",
        depth=0,
    )


MD = """# 文档标题

## 一、文档元信息
元信息内容

### 1.1 变更日志
不该成为功能点的变更记录

## 5.1 头条账户授权管理
管理广告主账户。

### 5.1.1 批量投放人
批量修改投放人逻辑。

#### 5.1.1.1 确认解绑
解绑确认弹窗。

## 5.2 漫剧库
展示可投放漫剧列表。

### 5.2.1 列字段说明
列字段定义。
"""


def test_meta_headings_dropped():
    sections = _extract_sections(_result(MD), doc_type="prd")
    headings = [s.heading for s in sections]
    assert "一、文档元信息" not in headings
    assert "1.1 变更日志" not in headings  # 元信息子树整体丢弃


def test_feature_granularity_is_module_level():
    sections = _extract_sections(_result(MD), doc_type="prd")
    headings = [s.heading for s in sections]
    # 只保留二级功能模块，深层 5.1.1 / 5.1.1.1 折叠进父模块，不单独成段
    assert "5.1 头条账户授权管理" in headings
    assert "5.2 漫剧库" in headings
    assert "5.1.1 批量投放人" not in headings
    assert "5.1.1.1 确认解绑" not in headings


def test_deeper_levels_folded_into_parent_content():
    sections = _extract_sections(_result(MD), doc_type="prd")
    s51 = next(s for s in sections if s.heading == "5.1 头条账户授权管理")
    # 父模块正文应包含被折叠的子标题与其内容，保证上下文完整
    assert "批量修改投放人逻辑" in s51.content
    assert "解绑确认弹窗" in s51.content
    assert "5.1.1" in s51.content


def test_no_heading_falls_back_to_whole_content():
    sections = _extract_sections(_result("纯文本无标题的需求描述"), doc_type="prd")
    assert len(sections) == 1
    assert "纯文本" in sections[0].content


def test_public_pilot_adapter_uses_the_same_section_boundaries():
    source = _result(MD)

    production_sections = _extract_sections(source, doc_type="prd")
    pilot_sections = extract_document_sections(
        document_id=source.document_id,
        title=source.title,
        content=source.content_snippet,
        doc_type="prd",
    )

    assert pilot_sections == production_sections


async def test_seed_adapter_uses_real_title_and_same_semantic_segmentation(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_roles(title, triples, *, strict=False):
        captured.update(title=title, triples=triples, strict=strict)
        return {0: "container", 1: "feature_root"}

    monkeypatch.setattr("src.testcase_generator.stages.parse.node.decide_feature_roles", fake_roles)
    content = "# 功能方案\n\n## 商品同步\n每天同步上游商品。\n"

    sections = await extract_seed_document_sections(
        document_id=uuid4(),
        title="分销系统 v1.2 新增结算单功能",
        content=content,
        doc_type="prd",
        semantic_segmentation=True,
        strict=True,
    )

    assert captured["title"] == "分销系统 v1.2 新增结算单功能"
    assert captured["strict"] is True
    assert [section.heading for section in sections] == ["商品同步"]


def test_taxonomy_inventory_covers_every_markdown_body_without_semantic_dropping():
    content = """封面前言也需要进入分母。

# 文档标题
总说明。

## 版本记录
元信息内容。

## 商品管理
商品列表展示同步数据。

### 商品下架
下架后展示下架状态。
"""

    sections = extract_document_inventory_sections(
        document_id=uuid4(),
        title="商品 PRD",
        content=content,
        doc_type="prd",
    )

    assert [section.heading for section in sections] == [
        "商品 PRD（标题前正文）",
        "文档标题",
        "文档标题 › 版本记录",
        "文档标题 › 商品管理",
        "文档标题 › 商品管理 › 商品下架",
    ]
    assert "元信息内容" in sections[2].content
    assert "下架后展示下架状态" in sections[-1].content
    assert len({section.source_ref for section in sections}) == len(sections)


def test_taxonomy_inventory_disambiguates_duplicate_heading_paths():
    sections = extract_document_inventory_sections(
        document_id=uuid4(),
        title="重复标题 PRD",
        content="# 文档\n\n## 规则\n第一条。\n\n## 规则\n第二条。",
        doc_type="prd",
    )

    duplicate_refs = [section.source_ref for section in sections if section.heading.endswith("规则")]
    assert len(duplicate_refs) == 2
    assert duplicate_refs[0] != duplicate_refs[1]


# ── 根因1：补全 meta 关键词 ────────────────────────────────────────────────────

VERSION_RECORD_MD = """# 文档标题
概述正文。

# 版本记录

| 时间 | 版本 | 变更内容 | 变更人 |
| -- | -- | -- | -- |
| 2026.05.28 | v1.0 | 初稿 | 张三 |

# 2. 需求说明
正式功能：用户可在系统中登录并查看数据。
"""


def test_version_record_heading_dropped():
    # "版本记录"(谁何时改了什么)是纯元信息，不应成为功能点
    sections = _extract_sections(_result(VERSION_RECORD_MD), doc_type="prd")
    headings = [s.heading for s in sections]
    assert "版本记录" not in headings
    assert any("需求说明" in h for h in headings)


# ── 根因2a：同源二级章节合并 ───────────────────────────────────────────────────

COHESIVE_MD = """# 3. CP书籍数据权限控制

## 3.1 功能说明
在【CP商管理】中新增【负责人】字段，用于控制【CP选书】页面的数据权限。

## 3.2 配置规则
【CP商管理】中新增【负责人】字段，负责人配置后仅对应负责人可在【CP选书】页面查看该 CP 商相关数据。

## 3.3 权限规则
超管不受【负责人】字段限制，可查看全部 CP 商选书数据；非超管仅可查看本人负责的 CP 商选书数据。
"""


def test_cohesive_subsections_merge_to_parent_feature():
    # 同一功能的「功能说明/配置规则/权限规则」判别性术语高度共享 → 退回一级粒度合并
    sections = _extract_sections(_result(COHESIVE_MD), doc_type="prd")
    headings = [s.heading for s in sections]
    assert "3. CP书籍数据权限控制" in headings
    assert "3.1 功能说明" not in headings
    assert "3.2 配置规则" not in headings
    parent = next(s for s in sections if s.heading == "3. CP书籍数据权限控制")
    assert "负责人" in parent.content and "超管" in parent.content


NON_COHESIVE_MD = """# 平台 PRD
## 5.1 账户授权管理
管理广告主账户与授权，支持新增、编辑、解绑广告主账户。
## 5.2 漫剧库展示
展示可投放漫剧列表与详情，支持按题材筛选漫剧。
## 5.3 投放计划编辑
编辑投放计划的预算、排期与定向人群配置。
## 5.4 数据报表导出
导出投放效果统计报表，支持多维度汇总与下载。
"""


def test_distinct_features_stay_module_level():
    # 4 个二级标题各讲不同功能、判别性术语不共享 → 保持二级粒度，不被误合并(零回归)
    sections = _extract_sections(_result(NON_COHESIVE_MD), doc_type="prd")
    headings = [s.heading for s in sections]
    assert "5.1 账户授权管理" in headings
    assert "5.2 漫剧库展示" in headings
    assert "5.3 投放计划编辑" in headings
    assert "5.4 数据报表导出" in headings
