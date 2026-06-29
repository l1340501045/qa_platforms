"""LLM 客户端 — 单一 OpenAI 兼容网关 + 主模型重试 + structured output + 调用统计

通过 settings.llm_base_url 指向自建网关（OpenAI 兼容协议）。
只调主模型，失败重试主模型，重试耗尽才报错；不切备用模型。
支持多模态：传 images 参数时用 vision model + multimodal messages。
"""

import base64
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


def _salvage_json(text: str) -> dict | None:
    """抢救被截断/损坏的 JSON：单遍扫描，截到最后一个「完整元素边界」再补齐闭合括号。

    应对网关偶发吐出中途截断的 JSON（典型报错 `Expecting ',' delimiter`）。
    安全边界 = 容器闭合（`}`/`]`）之后，或「数组内」的逗号之前——此处之前必是若干完整元素，
    截断到此并补上未闭合的括号即得最长合法前缀。仅作重试耗尽后的兜底，可能丢失尾部不完整元素。
    无法抢救返回 None。
    """
    start = text.find("{")
    if start == -1:
        return None
    s = text[start:]
    stack: list[str] = []
    in_str = esc = False
    best_cut = -1
    best_close = ""
    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if stack:
                stack.pop()
            best_cut, best_close = i + 1, "".join(reversed(stack))
        elif ch == "," and stack and stack[-1] == "]":
            # 仅「数组内」的逗号是安全截断点（其前是完整元素）；对象内字段逗号会救出残缺对象，不取
            best_cut, best_close = i, "".join(reversed(stack))
    if best_cut <= 0:
        return None
    try:
        result = json.loads(s[:best_cut] + best_close)
        return result if isinstance(result, dict) else None
    except json.JSONDecodeError:
        return None


class _GatewayJSONError(Exception):
    """网关返回的 JSON 解析失败（携带原始内容，供重试耗尽后抢救最长合法前缀）。"""

    def __init__(self, content: str) -> None:
        super().__init__("网关返回 JSON 解析失败")
        self.content = content


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
        images: list[bytes] | None = None,
        model: str | None = None,
    ) -> T:
        """调用主模型并强制输出为指定 schema；失败重试主模型，不切备用模型。

        传 images 时使用 vision model + multimodal messages；不传时走纯文本路径。
        """
        if images and not settings.llm_vision_model:
            raise ValueError("图解析需配置 LLM_VISION_MODEL 环境变量")

        model = model or (settings.llm_vision_model if images else self.primary_model)
        schema_name = output_schema.__name__
        attempt_count = 0
        start_time = time.monotonic()

        @retry(
            stop=stop_after_attempt(settings.llm_max_retries),
            wait=wait_exponential(min=1, max=10),
            before_sleep=lambda rs: logger.warning(
                f"model {model} attempt {rs.attempt_number} failed, "
                f"retrying: {rs.outcome.exception()}"
            ),
            reraise=True,
        )
        async def _attempt() -> T:
            nonlocal attempt_count
            attempt_count += 1
            return await self._call(model, system_prompt, user_content, output_schema, temperature, images=images)

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
                "LLM 调用成功: schema=%s model=%s attempts=%d duration=%.1fs",
                schema_name,
                model,
                attempt_count,
                duration_ms / 1000,
            )
            return result
        except _GatewayJSONError as e:
            # 重试耗尽仍是损坏 JSON → 抢救最长合法前缀（可能丢尾部元素），避免整批丢失
            salvaged = _salvage_json(e.content)
            if salvaged is not None:
                try:
                    result = output_schema.model_validate(salvaged)
                except Exception:  # noqa: BLE001 — 抢救结果不满足 schema，按失败处理
                    result = None
                if result is not None:
                    duration_ms = (time.monotonic() - start_time) * 1000
                    llm_stats.record(
                        CallStats(
                            schema_name=schema_name,
                            attempts=attempt_count,
                            success=True,
                            duration_ms=duration_ms,
                            error="salvaged_truncated_json",
                        )
                    )
                    logger.warning(
                        "JSON 多次损坏，已抢救最长合法前缀（可能丢尾部元素）: schema=%s attempts=%d",
                        schema_name,
                        attempt_count,
                    )
                    return result
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
        images: list[bytes] | None = None,
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

        if images:
            user_msg_content: list[dict] = [{"type": "text", "text": user_content}]
            for img_bytes in images:
                b64 = base64.b64encode(img_bytes).decode()
                user_msg_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                })
            messages = [
                {"role": "system", "content": system_prompt + schema_instruction},
                {"role": "user", "content": user_msg_content},
            ]
        else:
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
                logger.info("从 tool_calls 提取内容 (finish_reason=tool_calls, content was empty)")

        logger.debug(f"raw_finish={finish_reason} usage={usage} content_head={content[:500]!r}")

        # 兼容网关返回被 markdown code block 包裹的情况
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        try:
            parsed = _loads_tolerant(content)
        except json.JSONDecodeError as e:
            # 网关偶发返回截断/损坏 JSON：携原始内容上抛，重试耗尽后由 generate_structured 抢救
            raise _GatewayJSONError(content) from e
        return output_schema.model_validate(parsed)


# 延迟初始化单例（避免 import 时因缺少配置报错）
_llm_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """获取 LLM 客户端单例（首次调用时初始化）"""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
