"""OpenAI-compatible embedding adapter with configurable request timeout."""

from typing import Literal, Optional, override

from mem0.configs.embeddings.base import BaseEmbedderConfig
from mem0.embeddings.base import EmbeddingBase
from openai import OpenAI

from app.core.config import settings


class OpenAICompatibleEmbedding(EmbeddingBase):
    """Generate embeddings through an OpenAI-compatible API endpoint."""

    def __init__(self, config: Optional[BaseEmbedderConfig] = None) -> None:
        """Initialize the embedding client from mem0 and application settings."""
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
        )

    @override
    def embed(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        text: str,
        memory_action: Optional[Literal["add", "search", "update"]] = None,
    ) -> list[float]:
        """Return an embedding vector for the supplied text."""
        response = self.client.embeddings.create(
            input=[text.replace("\n", " ")],
            model=self._model,
            dimensions=self._embedding_dims,
        )
        return list(response.data[0].embedding)
