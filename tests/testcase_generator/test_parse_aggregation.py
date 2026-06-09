"""回归测试：parse 按"功能模块"粒度聚合标题，丢弃非功能元信息段。

根因背景：原实现把每个 markdown 标题（含 4 级细节、变更日志/背景等元信息）
都当成一个功能点，真实 PRD 切出 127 个碎片 →（1）同一功能上下文被切散，
AI 理解不准、用例质量下降；（2）对"变更日志"等非功能段生成无意义用例。
聚合后：以二级标题为模块粒度、深层折叠进父模块、元信息整树丢弃。
"""

from src.knowledge_base.schemas.common import SearchResult
from src.testcase_generator.stages.parse.node import _extract_sections
from uuid import uuid4


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
