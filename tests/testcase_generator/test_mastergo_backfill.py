"""落点⑦ 迁移工具纯函数测试：噪音过滤 + 幂等回灌注入。"""

from src.testcase_generator.stages.parse.mastergo_fetch import (
    BACKFILL_SENTINEL,
    build_backfill_block,
    filter_promo_digests,
    inject_backfill_block,
)


def test_filter_promo_drops_mastergo_ads():
    """MasterGo 自带广告/模板帧应被滤除，真实业务屏保留。"""
    items = [
        ("审核记录", "审核状态 / 待提审 / 审核通过 / 申请签约"),
        ("editorial-artboard", "MasterGo MCP / 赋予 AI 掌控画布的原生能力 / access key"),
    ]
    kept = filter_promo_digests(items)
    assert len(kept) == 1
    assert kept[0][0] == "审核记录"


def test_filter_promo_keeps_all_business():
    items = [("列表", "字段A / 字段B"), ("新建", "权限：非责编→您暂无权限")]
    assert len(filter_promo_digests(items)) == 2


def test_build_block_has_sentinels_and_content():
    block = build_backfill_block({"https://mastergo.com/file/1?page_id=2": "· 列表：字段A / 字段B"})
    assert BACKFILL_SENTINEL in block
    assert "原型规格补全" in block
    assert "字段A" in block


def test_build_block_empty_returns_empty():
    assert build_backfill_block({}) == ""


def test_inject_idempotent_and_replaces():
    base = "# PRD\n正文内容……\n见原型 https://mastergo.com/file/1?page_id=2"
    block1 = build_backfill_block({"https://mastergo.com/file/1?page_id=2": "· 列表：字段A / 字段B"})
    once = inject_backfill_block(base, block1)
    block2 = build_backfill_block({"https://mastergo.com/file/1?page_id=2": "· 列表：字段A / 字段B / 字段C"})
    twice = inject_backfill_block(once, block2)

    assert once.count(BACKFILL_SENTINEL) == 1
    assert twice.count(BACKFILL_SENTINEL) == 1  # 复跑不重复，整块替换
    assert "字段C" in twice  # 替换为最新
    assert "正文内容……" in twice  # PRD 原文保留


def test_inject_empty_block_is_noop():
    base = "# PRD\n无原型链接的普通文档"
    assert inject_backfill_block(base, "") == base
