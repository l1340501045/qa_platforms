"""OpenAI Embedding 客户端 — 批量调用 + 重试"""

import logging
from typing import Sequence

import openai
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.knowledge_base.config import kb_settings
from src.platform_api.core.model_runtime import (
    EMBEDDING_DIMENSION,
    ModelConfigBundle,
    ModelRole,
    build_environment_model_bundle,
    get_current_model_bundle,
)

logger = logging.getLogger(__name__)

# 单次 API 调用的最大文本数
# 注：自建网关的 text-embedding-v4(通义) 单批上限为 10，超过会返回 400 InvalidParameter
_MAX_BATCH_SIZE = 10


class EmbeddingDimensionError(ValueError):
    """向量模型返回维度与数据库固定维度不一致。"""

    def __init__(self, actual_dimension: int):
        self.actual_dimension = actual_dimension
        super().__init__(f"向量模型返回 {actual_dimension} 维，平台要求固定为 {EMBEDDING_DIMENSION} 维")


class EmbeddingResponseError(ValueError):
    """向量响应结构不完整；消息只包含平台生成的固定文案。"""


class EmbeddingInvocationError(RuntimeError):
    """对外隐藏供应商异常正文，避免日志或任务结果泄露敏感内容。"""

    def __init__(self, cause_type: str):
        self.cause_type = cause_type
        super().__init__(f"{cause_type}: 向量模型调用失败")


class EmbeddingClient:
    """OpenAI Embedding API 封装"""

    def __init__(self, bundle: ModelConfigBundle | None = None) -> None:
        fallback = build_environment_model_bundle(kb_settings)
        self.bundle = bundle or get_current_model_bundle(fallback)
        endpoint = self.bundle.for_role(ModelRole.EMBEDDING)
        self._client = openai.AsyncOpenAI(
            api_key=endpoint.api_key or "local-no-key",
            base_url=endpoint.base_url,
        )
        self._model = endpoint.model_name
        if not self._model:
            raise ValueError("向量模型名称未配置")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((openai.RateLimitError, openai.APITimeoutError)),
        reraise=True,
    )
    async def _create_embeddings(self, texts: Sequence[str]):
        return await self._client.embeddings.create(
            input=list(texts),
            model=self._model,
        )

    async def embed_single(self, text: str) -> list[float]:
        """获取单条文本的 embedding 向量。"""
        if not text.strip():
            return []
        try:
            response = await self._create_embeddings([text])
            if not response.data:
                raise EmbeddingResponseError("向量模型返回空结果")
            embedding = response.data[0].embedding
            self._validate_dimension(embedding)
            logger.info(
                "Embedding 调用成功: role=embedding model=%s revision=%d items=1",
                self._model,
                self.bundle.revision,
            )
            return embedding
        except (EmbeddingDimensionError, EmbeddingResponseError):
            raise
        except Exception as exc:
            raise EmbeddingInvocationError(type(exc).__name__) from None

    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """批量获取 embedding 向量"""
        if not texts:
            return []

        try:
            all_embeddings: list[list[float]] = []

            # 分批调用
            for i in range(0, len(texts), _MAX_BATCH_SIZE):
                batch = texts[i : i + _MAX_BATCH_SIZE]
                # 过滤空字符串
                batch = [t if t.strip() else " " for t in batch]

                response = await self._create_embeddings(batch)
                if len(response.data) != len(batch):
                    raise EmbeddingResponseError("向量模型返回条数与请求不一致")
                batch_embeddings = [item.embedding for item in response.data]
                for embedding in batch_embeddings:
                    self._validate_dimension(embedding)
                all_embeddings.extend(batch_embeddings)

            logger.info(
                "Embedding 调用成功: role=embedding model=%s revision=%d items=%d",
                self._model,
                self.bundle.revision,
                len(all_embeddings),
            )
            return all_embeddings
        except (EmbeddingDimensionError, EmbeddingResponseError):
            raise
        except Exception as exc:
            raise EmbeddingInvocationError(type(exc).__name__) from None

    @staticmethod
    def _validate_dimension(embedding: Sequence[float]) -> None:
        if len(embedding) != EMBEDDING_DIMENSION:
            raise EmbeddingDimensionError(len(embedding))
