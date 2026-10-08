"""OpenAI 兼容接口的 embedding 适配器，请求超时可配."""

from typing import Literal, Optional, override

from mem0.configs.embeddings.base import BaseEmbedderConfig
from mem0.embeddings.base import EmbeddingBase
from openai import OpenAI

from app.core.config import settings


class OpenAICompatibleEmbedding(EmbeddingBase):
    """通过 OpenAI 兼容的 API 端点生成向量."""

    def __init__(self, config: Optional[BaseEmbedderConfig] = None) -> None:
        """用 mem0 传来的配置加上应用设置，初始化 embedding 客户端."""
        super().__init__(config)
        self._model = self.config.model or settings.LONG_TERM_MEMORY_EMBEDDER_MODEL
        self._embedding_dims = self.config.embedding_dims or settings.EMBEDDING_DIM
        self.config.model = self._model
        self.config.embedding_dims = self._embedding_dims
        api_key = self.config.api_key or settings.EMBEDDING_API_KEY
        base_url = self.config.openai_base_url or settings.EMBEDDING_BASE_URL
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=settings.EMBEDDING_TIMEOUT_SECONDS,
            max_retries=0,
        )

    @override
    def embed(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        text: str,
        memory_action: Optional[Literal["add", "search", "update"]] = None,
    ) -> list[float]:
        """返回给定文本对应的向量."""
        client = self.client
        if memory_action == "search":
            client = client.with_options(
                timeout=min(settings.EMBEDDING_TIMEOUT_SECONDS, settings.MEMORY_SEARCH_TIMEOUT_SECONDS)
            )
        response = client.embeddings.create(
            input=[text.replace("\n", " ")],
            model=self._model,
            dimensions=self._embedding_dims,
        )
        return list(response.data[0].embedding)
