"""Task 0.1 — 章节树切分器测试。

验证：meta 章节整树丢弃、功能模块切成独立单元、EOF 越界已修（任何单元不超过全文长度）。
"""

from __future__ import annotations

from src.testcase_generator.stages.rule_extract.splitter import build_units

MD = """# 一、文档元信息
作者：x
## 1.2 变更日志
| 时间 | 版本 |
| --- | --- |
| 2026 | v1 |
# 五、功能详述
## 5.1 账户授权
投手只能看本人触发的授权记录，不能看他人记录。组长可查看本组全部成员的授权记录。管理员可查看全量授权记录。授权变更后立即生效，无需刷新页面。授权记录按时间倒序展示，支持按投手筛选。
## 5.8 批量创建
### 5.8.1 漫剧选择
默认空，不预填漫剧名。切换漫剧清空已选链接与素材。
### 5.8.13 提交逻辑
提交先弹确认框，立即提交或定时提交二选一。定时仅自然日。
"""


def test_meta_dropped_and_units_built():
    units, digest, clog = build_units(MD)
    titles = [u["title"] for u in units]
    # 变更日志/文档元信息属 meta，必须不在规则单元里
    assert not any("变更日志" in t or "文档元信息" in t for t in titles)
    # 5.1 作为独立模块单元
    assert any("5.1" in t for t in titles)
    # digest/classify_log 形态正确
    assert isinstance(digest, str)
    assert all(c["kind"] in {"meta", "digest", "rule"} for c in clog)


def test_no_unit_exceeds_eof_bound():
    # 修复 EOF 越界：任何单元字符数不得超过全文长度（真正有效的回归断言）
    units, _, _ = build_units(MD)
    assert units, "应至少切出一个规则单元"
    assert all(u["chars"] <= len(MD) for u in units)


def test_short_body_units_skipped():
    # 正文过短（纯标题/导航占位）的块不进规则抽取
    md = "# 五、功能详述\n## 5.0 概述\n短\n## 5.1 授权\n" + "投手只能看本人记录。" * 10
    units, _, _ = build_units(md)
    titles = [u["title"] for u in units]
    assert any("5.1" in t for t in titles)
    assert not any("5.0" in t for t in titles)
