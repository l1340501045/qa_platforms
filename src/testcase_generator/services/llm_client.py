"""LLM 客户端 — 单一 OpenAI 兼容网关 + 主模型重试 + structured output + 调用统计

通过 settings.llm_base_url 指向自建网关（OpenAI 兼容协议）。
只调主模型，失败重试主模型，重试耗尽才报错；不切备用模型。
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Type, TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential

from src.platform_api.core.settings import settings

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


@dataclass
class CallStats:
    """单次 generate_structured 调用的统计"""

    schema_name: str
    attempts: int  # 第几次成功（1=首次成功）
    success: bool
    duration_ms: float
    error: str | None = None


@dataclass
class LLMStats:
    """全局统计收集器"""

    calls: list[CallStats] = field(default_factory=list)

    def record(self, stats: CallStats) -> None:
        self.calls.append(stats)

    def report(self) -> str:
        """输出统计报告"""
        if not self.calls:
            return "无 LLM 调用记录"

        lines = ["=== LLM 调用统计 ==="]
        total = len(self.calls)
        success = sum(1 for c in self.calls if c.success)
        first_attempt_success = sum(1 for c in self.calls if c.success and c.attempts == 1)

        lines.append(f"总调用: {total} | 成功: {success} | 失败: {total - success}")
        lines.append(
            f"首次成功率: {first_attempt_success}/{success} = {first_attempt_success / max(success, 1) * 100:.0f}%"
        )

        # 按 schema 分组
        by_schema: dict[str, list[CallStats]] = {}
        for c in self.calls:
            by_schema.setdefault(c.schema_name, []).append(c)

        for schema, calls in by_schema.items():
            s = sum(1 for c in calls if c.success)
            f1 = sum(1 for c in calls if c.success and c.attempts == 1)
            avg_attempts = sum(c.attempts for c in calls if c.success) / max(s, 1)
            avg_ms = sum(c.duration_ms for c in calls) / len(calls)
            lines.append(
                f"  {schema}: {len(calls)}次调用 | 首次成功率 {f1}/{s} ({f1 / max(s, 1) * 100:.0f}%) "
                f"| 平均尝试 {avg_attempts:.1f}次 | 平均耗时 {avg_ms / 1000:.1f}s"
            )

        return "\n".join(lines)


# 全局统计实例
llm_stats = LLMStats()


def _is_response_format_unsupported(err: Exception) -> bool:
    """判断异常是否为「网关不支持 response_format 参数」，用于一次性永久回退。

    不同网关报法不一（400 + 'response_format'/'json_object'/'unsupported'/'unknown
    parameter'），统一按错误文本启发式判断；网络/超时类错误不在此列（应照常重试）。
    """
    msg = str(err).lower()
    if "response_format" in msg or "json_object" in msg or "json mode" in msg:
        return True
    markers = ("unsupported", "not support", "unknown parameter", "unrecognized", "invalid parameter")
    return any(m in msg for m in markers) and "param" in msg


def _loads_tolerant(content: str) -> dict:
    """更鲁棒的 JSON 解析：先直接解析，失败则裁剪到首尾大括号之间再试。

    应对网关偶发的前后缀噪声（如解释性文字、思维链前缀）。
    """
    text = (content or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


class LLMClient:
    """统一 LLM 调用封装

    - 单一 OpenAI 兼容客户端：base_url / api_key / model 全部可配，指向自建网关
    - 只调主模型：失败按 LLM_MAX_RETRIES 重试主模型，重试耗尽才报错；不切备用模型
    - Structured output：传入 Pydantic model，schema 注入 prompt 强约束并校验
    - 调用统计：记录每次调用的尝试次数和耗时
    - 质量优先不设 token/时间上限
    """

    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.resolved_llm_api_key,
            base_url=settings.resolved_llm_base_url,
            timeout=settings.llm_timeout,
        )
        self.primary_model = settings.llm_primary_model
        if not self.primary_model:
            raise ValueError("LLM_PRIMARY_MODEL 未配置：请在 .env 中设置 LLM_PRIMARY_MODEL")
        # JSON mode 开关：网关/后端不支持 response_format 时自动置 False 永久回退
        self._json_mode = settings.llm_json_mode

    async def generate_structured(
        self,
        system_prompt: str,
        user_content: str,
        output_schema: Type[T],
        temperature: float = 0.3,
    ) -> T:
        """调用主模型并强制输出为指定 schema；失败重试主模型，不切备用模型"""
        schema_name = output_schema.__name__
        attempt_count = 0
        start_time = time.monotonic()

        @retry(
            stop=stop_after_attempt(settings.llm_max_retries),
            wait=wait_exponential(min=1, max=10),
            before_sleep=lambda rs: logger.warning(
                f"primary model {self.primary_model} attempt {rs.attempt_number} failed, "
                f"retrying: {rs.outcome.exception()}"
            ),
            reraise=True,
        )
        async def _attempt() -> T:
            nonlocal attempt_count
            attempt_count += 1
            return await self._call(self.primary_model, system_prompt, user_content, output_schema, temperature)

        try:
            result = await _attempt()
            duration_ms = (time.monotonic() - start_time) * 1000
            llm_stats.record(
                CallStats(
                    schema_name=schema_name,
                    attempts=attempt_count,
                    success=True,
                    duration_ms=duration_ms,
                )
            )
            logger.info(
                f"LLM 调用成功: schema={schema_name} attempts={attempt_count} duration={duration_ms / 1000:.1f}s"
            )
            return result
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            llm_stats.record(
                CallStats(
                    schema_name=schema_name,
                    attempts=attempt_count,
                    success=False,
                    duration_ms=duration_ms,
                    error=str(e),
                )
            )
            raise

    async def _call(
        self,
        model: str,
        system_prompt: str,
        user_content: str,
        output_schema: Type[T],
        temperature: float,
    ) -> T:
        """单次调用（OpenAI 兼容 JSON mode + 加强 schema 约束 + 校验）"""
        schema_json = json.dumps(output_schema.model_json_schema(), ensure_ascii=False, indent=2)

        # 加强 JSON 约束：明确禁止解释性文字 + 给极简合法样例骨架
        required_fields = list(output_schema.model_fields.keys())
        example_skeleton = "{" + ", ".join(f'"{f}": ...' for f in required_fields) + "}"

        schema_instruction = (
            "\n\n【输出格式强约束】\n"
            "1. 仅输出合法 JSON，禁止任何解释性文字、markdown 包裹或注释\n"
            "2. JSON 必须包含以下顶层字段：" + ", ".join(f'"{f}"' for f in required_fields) + "\n"
            f"3. 合法输出骨架示例：{example_skeleton}\n"
            f"4. 完整 JSON Schema：\n{schema_json}"
        )

        messages = [
            {"role": "system", "content": system_prompt + schema_instruction},
            {"role": "user", "content": user_content},
        ]

        # JSON mode：让网关/后端在解码层就只产出合法 JSON，根治长输出的分隔符/截断错误。
        # 网关不支持 response_format 时（通常报 400/不识别参数）一次性永久回退到纯 prompt 约束。
        if self._json_mode:
            try:
                response = await self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    response_format={"type": "json_object"},
                )
            except Exception as e:  # noqa: BLE001 — 仅针对 response_format 不被支持的回退
                if _is_response_format_unsupported(e):
                    logger.warning("网关不支持 response_format=json_object，永久回退纯 prompt 约束: %s", e)
                    self._json_mode = False
                    response = await self.client.chat.completions.create(
                        model=model, messages=messages, temperature=temperature
                    )
                else:
                    raise
        else:
            response = await self.client.chat.completions.create(
                model=model, messages=messages, temperature=temperature
            )

        content = response.choices[0].message.content or ""
        finish_reason = response.choices[0].finish_reason
        usage = response.usage

        # 网关可能把 JSON 输出放在 tool_calls 里（而非 content）
        # 当 finish_reason=tool_calls 且 content 为空/仅 {} 时，从 tool_calls 提取
        if finish_reason == "tool_calls" and (not content.strip() or content.strip() == "{}"):
            tool_calls = response.choices[0].message.tool_calls
            if tool_calls and tool_calls[0].function.arguments:
                content = tool_calls[0].function.arguments
                logger.info(f"从 tool_calls 提取内容 (finish_reason=tool_calls, content was empty)")

        logger.debug(f"raw_finish={finish_reason} usage={usage} content_head={content[:500]!r}")

        # 兼容网关返回被 markdown code block 包裹的情况
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        parsed = _loads_tolerant(content)
        return output_schema.model_validate(parsed)


# 延迟初始化单例（避免 import 时因缺少配置报错）
_llm_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """获取 LLM 客户端单例（首次调用时初始化）"""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
