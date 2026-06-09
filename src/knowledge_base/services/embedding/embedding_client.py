"""OpenAI Embedding 客户端 — 批量调用 + 重试"""

import logging
from typing import Sequence

import openai
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.knowledge_base.config import kb_settings

logger = logging.getLogger(__name__)

# 单次 API 调用的最大文本数（OpenAI 限制）
_MAX_BATCH_SIZE = 2048


class EmbeddingClient:
    """OpenAI Embedding API 封装"""

    def __init__(self) -> None:
        self._client = openai.AsyncOpenAI(
            api_key=kb_settings.resolved_embedding_api_key,
            base_url=kb_settings.resolved_embedding_base_url,
        )
        self._model = kb_settings.openai_embedding_model

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((openai.RateLimitError, openai.APITimeoutError)),
        reraise=True,
    )
    async def embed_single(self, text: str) -> list[float]:
        """获取单条文本的 embedding 向量"""
        if not text.strip():
            return []
        response = await self._client.embeddings.create(
            input=[text],
            model=self._model,
        )
        return response.data[0].embedding

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((openai.RateLimitError, openai.APITimeoutError)),
        reraise=True,
    )
    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """批量获取 embedding 向量"""
        if not texts:
            return []

        all_embeddings: list[list[float]] = []

        # 分批调用
        for i in range(0, len(texts), _MAX_BATCH_SIZE):
            batch = texts[i : i + _MAX_BATCH_SIZE]
            # 过滤空字符串
            batch = [t if t.strip() else " " for t in batch]

            response = await self._client.embeddings.create(
                input=batch,
                model=self._model,
            )
            batch_embeddings = [item.embedding for item in response.data]
            all_embeddings.extend(batch_embeddings)

        return all_embeddings
