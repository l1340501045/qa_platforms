"""四类 OpenAI 兼容模型的真实能力测试。"""

import asyncio
import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import Any

import openai

from src.platform_api.core.model_runtime import EMBEDDING_DIMENSION, ModelEndpointConfig, ModelRole

_RED_PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAF0lEQVR4nGP4z8BAEiJN9aiGUQ1DSgMAkPn/"
    "Afnh+ngAAAAASUVORK5CYII="
)


class ModelCapabilityError(RuntimeError):
    pass


class ModelDimensionError(RuntimeError):
    def __init__(self, actual_dimension: int):
        self.actual_dimension = actual_dimension
        super().__init__("向量维度不匹配")


@dataclass(frozen=True)
class ConnectionTestResult:
    ok: bool
    category: str
    message: str
    latency_ms: int
    embedding_dimension: int | None = None


class ModelConnectionTester:
    """使用一次性客户端测试对应模型能力，不重试也不泄漏供应商错误。"""

    def __init__(
        self,
        *,
        timeout: float = 20.0,
        client_factory: Callable[..., Any] = openai.AsyncOpenAI,
    ):
        self.timeout = timeout
        self.client_factory = client_factory

    async def test(self, endpoint: ModelEndpointConfig) -> ConnectionTestResult:
        started_at = monotonic()
        client: Any | None = None
        try:
            client = self.client_factory(
                api_key=endpoint.api_key or "local-no-key",
                base_url=endpoint.base_url,
                timeout=self.timeout,
                max_retries=0,
            )
            dimension = await asyncio.wait_for(self._test_capability(client, endpoint), timeout=self.timeout)
            return ConnectionTestResult(
                ok=True,
                category="success",
                message="连接与模型能力测试成功",
                latency_ms=self._latency_ms(started_at),
                embedding_dimension=dimension,
            )
        except ModelDimensionError as exc:
            return ConnectionTestResult(
                ok=False,
                category="dimension_mismatch",
                message=f"向量模型返回 {exc.actual_dimension} 维，平台要求固定为 {EMBEDDING_DIMENSION} 维",
                latency_ms=self._latency_ms(started_at),
                embedding_dimension=exc.actual_dimension,
            )
        except ModelCapabilityError:
            return self._failure("capability_mismatch", "接口可访问，但不支持所需的模型能力", started_at)
        except (openai.AuthenticationError, openai.PermissionDeniedError):
            return self._failure("authentication", "API Key 无效，或无权使用该模型", started_at)
        except openai.NotFoundError:
            return self._failure("model_not_found", "模型不存在，或当前账号无权访问", started_at)
        except openai.RateLimitError:
            return self._failure("rate_limit", "模型服务当前限流，请稍后重试", started_at)
        except (asyncio.TimeoutError, openai.APITimeoutError, openai.APIConnectionError):
            return self._failure("network", "无法连接模型服务，请检查地址和网络", started_at)
        except openai.BadRequestError:
            return self._failure("capability_mismatch", "模型接口不兼容当前能力测试", started_at)
        except Exception:
            return self._failure("unknown", "连接测试失败，请检查配置后重试", started_at)
        finally:
            await self._close_client(client)

    async def _test_capability(self, client: Any, endpoint: ModelEndpointConfig) -> int | None:
        if endpoint.role is ModelRole.EMBEDDING:
            response = await client.embeddings.create(input=["qa model connection test"], model=endpoint.model_name)
            if not response.data:
                raise ModelCapabilityError("向量响应为空")
            dimension = len(response.data[0].embedding)
            if dimension != EMBEDDING_DIMENSION:
                raise ModelDimensionError(dimension)
            return dimension

        messages: list[dict[str, Any]]
        if endpoint.role is ModelRole.VISION:
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "图片主体是什么颜色？只回答颜色名称。"},
                        {"type": "image_url", "image_url": {"url": _RED_PNG_DATA_URL}},
                    ],
                }
            ]
        elif endpoint.role is ModelRole.VERIFY:
            messages = [{"role": "user", "content": '只输出 JSON：{"ok": true}'}]
        else:
            messages = [{"role": "user", "content": "只回答 OK"}]

        response = await client.chat.completions.create(
            model=endpoint.model_name,
            messages=messages,
            max_tokens=24,
            temperature=0,
        )
        content = self._response_text(response)
        if not content:
            raise ModelCapabilityError("聊天响应为空")
        if endpoint.role is ModelRole.VISION and not any(token in content.lower() for token in ("红", "red")):
            raise ModelCapabilityError("视觉响应未识别图片")
        if endpoint.role is ModelRole.VERIFY:
            try:
                parsed = json.loads(self._strip_json_fence(content))
            except (json.JSONDecodeError, TypeError) as exc:
                raise ModelCapabilityError("校验模型未返回 JSON") from exc
            if not isinstance(parsed, dict):
                raise ModelCapabilityError("校验模型未返回 JSON 对象")
        return None

    @staticmethod
    def _response_text(response: Any) -> str:
        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError, TypeError) as exc:
            raise ModelCapabilityError("聊天响应结构不兼容") from exc
        return content.strip() if isinstance(content, str) else ""

    @staticmethod
    def _strip_json_fence(content: str) -> str:
        stripped = content.strip()
        if stripped.startswith("```") and stripped.endswith("```"):
            lines = stripped.splitlines()
            if len(lines) >= 3:
                return "\n".join(lines[1:-1]).strip()
        return stripped

    @staticmethod
    def _latency_ms(started_at: float) -> int:
        return max(0, round((monotonic() - started_at) * 1000))

    def _failure(self, category: str, message: str, started_at: float) -> ConnectionTestResult:
        return ConnectionTestResult(
            ok=False,
            category=category,
            message=message,
            latency_ms=self._latency_ms(started_at),
        )

    @staticmethod
    async def _close_client(client: Any | None) -> None:
        if client is None:
            return
        close = getattr(client, "close", None)
        if not callable(close):
            return
        try:
            result = close()
            if inspect.isawaitable(result):
                await result
        except Exception:
            # 连接测试结果不应被清理阶段异常覆盖，也不记录供应商错误内容。
            return
