"""端到端验证脚本 — 用小需求跑完整 6 阶段流水线，验证 LLM 真实调用"""

import asyncio
import json
import logging
import sys
from uuid import uuid4

# 配置日志：打印 LLM 调用详情
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("e2e_verify")

# Monkey-patch LLM client 以捕获实际 prompt 和响应
_captured_calls: list[dict] = []


async def main():
    from src.testcase_generator.services.llm_client import get_llm_client, LLMClient

    # Patch few_shot_injector 模拟冷启动（无 DB 连接时返回空）
    from src.testcase_generator.stages.write_cases import few_shot_injector

    async def mock_load_samples(self, system_id, feature_types):
        """冷启动：无 DB 时返回空 few-shot（符合预期行为）"""
        logger.info("  [few-shot] 冷启动：返回空样本（DB 不可达/无数据）")
        return []

    few_shot_injector.FewShotInjector.load_samples = mock_load_samples

    # Patch _call 以捕获 prompt
    original_call = LLMClient._call

    async def patched_call(self, model, system_prompt, user_content, output_schema, temperature):
        logger.info(
            f"=== LLM 调用 ===\n  model: {model}\n  schema: {output_schema.__name__}\n  system_prompt 长度: {len(system_prompt)} chars\n  user_content 长度: {len(user_content)} chars"
        )
        _captured_calls.append(
            {
                "model": model,
                "schema": output_schema.__name__,
                "system_prompt": system_prompt,
                "user_content": user_content,
            }
        )
        result = await original_call(self, model, system_prompt, user_content, output_schema, temperature)
        logger.info(f"  → LLM 返回成功，解析为 {output_schema.__name__}")
        return result

    LLMClient._call = patched_call

    # 构造模拟输入状态（小需求：用户注册功能，3 个功能点）
    from src.testcase_generator.schemas.parsed_context import (
        ParsedContext,
        SourceItem,
        SectionExtract,
        FeatureItem,
    )
    from src.testcase_generator.schemas.pipeline_state import PipelineState

    mock_parsed_context = ParsedContext(
        sources=[
            SourceItem(
                doc_id=str(uuid4()),
                doc_type="prd",
                trust_level=1,
                title="用户注册功能 PRD",
                sections=[
                    SectionExtract(
                        heading="2.1 手机号注册",
                        content="用户可通过手机号+验证码完成注册。手机号必须是有效的中国大陆手机号（11位，1开头）。验证码为6位数字，有效期5分钟。同一手机号每天最多发送5次验证码。注册成功后自动登录并跳转首页。",
                        source_ref="PRD §2.1",
                    ),
                    SectionExtract(
                        heading="2.2 邮箱注册",
                        content="用户可通过邮箱+密码完成注册。密码长度8-20位，必须包含大写字母、小写字母和数字。邮箱格式校验通过后发送验证链接，用户点击链接完成激活。验证链接24小时内有效。",
                        source_ref="PRD §2.2",
                    ),
                    SectionExtract(
                        heading="2.3 注册限制",
                        content="同一手机号/邮箱只能注册一个账号。注册时需同意用户协议和隐私政策（必须勾选）。未成年用户（<18岁）注册需要家长授权。",
                        source_ref="PRD §2.3",
                    ),
                ],
            ),
            SourceItem(
                doc_id=str(uuid4()),
                doc_type="tech_doc",
                trust_level=2,
                title="注册接口技术文档",
                sections=[
                    SectionExtract(
                        heading="API: POST /api/v1/register",
                        content="请求体：{phone, sms_code} 或 {email, password}。响应：{user_id, token}。错误码：40001-手机号格式错误，40002-验证码错误/过期，40003-手机号已注册，40004-邮箱格式错误，40005-密码强度不足。",
                        source_ref="Tech §3.1",
                    ),
                ],
            ),
        ],
        features=[
            FeatureItem(
                id="F001",
                name="手机号注册",
                description="用户通过手机号+短信验证码完成注册",
                source_refs=["PRD §2.1"],
                feature_type="data_input",
            ),
            FeatureItem(
                id="F002",
                name="邮箱注册",
                description="用户通过邮箱+密码完成注册",
                source_refs=["PRD §2.2"],
                feature_type="data_input",
            ),
            FeatureItem(
                id="F003",
                name="注册限制规则",
                description="账号唯一性、协议勾选、未成年限制",
                source_refs=["PRD §2.3"],
                feature_type="business_rule",
            ),
        ],
        prototype_observations=None,
    )

    # === Stage 2: comprehend ===
    logger.info("\n" + "=" * 60 + "\n  Stage 2: comprehend（LLM 语义理解）\n" + "=" * 60)
    from src.testcase_generator.stages.comprehend.node import comprehend_node

    state: dict = {
        "document_id": str(uuid4()),
        "system_id": str(uuid4()),
        "batch_id": str(uuid4()),
        "parsed_context": mock_parsed_context,
    }
    result = await comprehend_node(state)
    logger.info(f"  Gate 结果: {result['gate_result']}")
    logger.info(f"  覆盖度: {result['comprehension_report'].understanding_coverage}")

    # === Stage 3: test-points ===
    logger.info("\n" + "=" * 60 + "\n  Stage 3: test-points（LLM 生成具体测试点）\n" + "=" * 60)
    from src.testcase_generator.stages.test_points.node import test_points_node

    state.update(result)
    tp_result = await test_points_node(state)
    test_points = tp_result["test_points"]
    logger.info(f"  生成测试点数: {len(test_points)}")
    for tp in test_points[:5]:
        logger.info(f"    {tp.id} [{tp.dimension}] {tp.description[:60]}...")

    # === Stage 4: write-cases ===
    logger.info("\n" + "=" * 60 + "\n  Stage 4: write-cases（LLM + few-shot 生成用例）\n" + "=" * 60)
    from src.testcase_generator.stages.write_cases.node import write_cases_node

    state.update(tp_result)
    cases_result = await write_cases_node(state)
    test_cases = cases_result["test_cases"]
    logger.info(f"  生成用例数: {len(test_cases)}")

    # === Stage 5: review ===
    logger.info("\n" + "=" * 60 + "\n  Stage 5: review（LLM 覆盖审计）\n" + "=" * 60)
    from src.testcase_generator.stages.review.node import review_node

    state.update(cases_result)
    review_result = await review_node(state)
    audit_report = review_result["audit_report"]
    final_cases = review_result["final_test_cases"]
    logger.info(
        f"  审计报告: total_tp={audit_report.total_test_points}, covered={audit_report.covered_test_points}, coverage={audit_report.dimension_coverage:.2f}, gaps={len(audit_report.gaps)}, additions={len(audit_report.additions)}"
    )
    logger.info(f"  最终用例数: {len(final_cases)}")

    # === Stage 6: export ===
    logger.info("\n" + "=" * 60 + "\n  Stage 6: export（双轨导出）\n" + "=" * 60)
    from src.testcase_generator.stages.export.node import export_node

    state.update(review_result)
    export_result = await export_node(state)
    yaml_output = export_result["yaml_output"]
    markdown_output = export_result["markdown_output"]
    logger.info(f"  YAML 长度: {len(yaml_output)} chars")
    logger.info(f"  Markdown 长度: {len(markdown_output)} chars")

    # === 输出结果 ===
    print("\n" + "=" * 80)
    print("  端到端验证结果（完整 6 阶段）")
    print("=" * 80)

    # 1. write-cases 的实际 prompt
    write_cases_call = next((c for c in _captured_calls if c["schema"] == "WriteCasesLLMOutput"), None)
    if write_cases_call:
        print("\n--- write-cases SYSTEM PROMPT ---")
        print(write_cases_call["system_prompt"][:2000])
        print("\n--- write-cases USER CONTENT (前 1500 chars) ---")
        print(write_cases_call["user_content"][:1500])
    else:
        print("❌ 未捕获到 write-cases LLM 调用!")

    # 2. 前 2-3 条用例完整输出
    print("\n--- 生成的测试用例（前 3 条）---")
    for case in test_cases[:3]:
        print(f"\n{'─' * 60}")
        print(f"ID: {case.id}")
        print(f"标题: {case.title}")
        print(f"优先级: {case.priority} | 维度: {case.dimensions}")
        print(f"前置条件: {case.preconditions}")
        print(f"步骤:")
        for step in case.steps:
            print(f"  {step.step_number}. 操作: {step.action}")
            print(f"     输入: {step.input_data}")
            print(f"     预期: {step.expected_result}")
        print(f"预期结果: {case.expected_results}")
        print(f"Provenance: derived_from={case.provenance.derived_from}, section={case.provenance.source_section}")
        print(f"Trust Level: {case.trust_level} | Confidence: {case.confidence_note}")

    # 3. Review + Export 结果
    print(f"\n--- Stage 5: Review 审计报告 ---")
    print(f"total_test_points: {audit_report.total_test_points}")
    print(f"covered_test_points: {audit_report.covered_test_points}")
    print(f"dimension_coverage: {audit_report.dimension_coverage:.2f}")
    print(f"gaps 数: {len(audit_report.gaps)}")
    print(f"补充用例数: {len(audit_report.additions)}")

    print(f"\n--- Stage 6: Export 导出内容 ---")
    print(f"YAML 输出前 800 chars:")
    print(yaml_output[:800])
    print(f"\nMarkdown 输出前 800 chars:")
    print(markdown_output[:800])

    # 4. LLM 调用统计
    print(f"\n--- LLM 调用统计 ---")
    print(f"总调用次数: {len(_captured_calls)}")
    for i, call in enumerate(_captured_calls, 1):
        print(f"  {i}. model={call['model']} schema={call['schema']}")

    if not _captured_calls:
        print("❌ 没有任何 LLM 调用发生！检查网关配置。")
        sys.exit(1)

    # 输出统计报告
    from src.testcase_generator.services.llm_client import llm_stats

    print(f"\n{llm_stats.report()}")

    print("\n✅ 完整 6 阶段端到端验证完成")


if __name__ == "__main__":
    asyncio.run(main())
