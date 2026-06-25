"""落点⑥ CoT 显式化 + 溯源接地 grounded provenance 单元测试"""

from src.testcase_generator.stages.write_cases import node as wc


def test_cot_section_constant_nonempty():
    assert isinstance(wc.COT_REASONING_SECTION, str) and "显式分步推理纪律" in wc.COT_REASONING_SECTION
    assert "只输出最终用例 JSON" in wc.COT_REASONING_SECTION
