"""LLM model registry with pre-initialized instances."""

from typing import (
    Any,
    Dict,
    List,
    cast,
)

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from app.core.config import settings
from app.core.logging import logger

_API_KEY = SecretStr(settings.OPENAI_API_KEY)


class LLMRegistry:
    """Registry of available LLM models with pre-initialized instances.

    This class maintains a list of LLM configurations and provides
    methods to retrieve them by name with optional argument overrides.
    """

    # The configured provider exposes an OpenAI-compatible endpoint. Keeping the
    # registry environment-driven prevents provider-specific fallback model names
    # from being sent to a different provider.
    LLMS: List[Dict[str, Any]] = [
        {
            "name": settings.DEFAULT_LLM_MODEL,
            "llm": ChatOpenAI(
                model=settings.DEFAULT_LLM_MODEL,
                api_key=_API_KEY,
                base_url=settings.OPENAI_BASE_URL,
                temperature=settings.DEFAULT_LLM_TEMPERATURE,
                timeout=settings.LLM_REQUEST_TIMEOUT,
                extra_body={"max_tokens": settings.MAX_TOKENS},
            ),
        },
    ]

    @classmethod
    def get(cls, model_name: str, **kwargs) -> BaseChatModel:
        """Get an LLM by name with optional argument overrides.

        When kwargs are provided a fresh ChatOpenAI instance is returned with
        those overrides applied, leaving the shared registry entry untouched.

        Args:
            model_name: Name of the model to retrieve.
            **kwargs: Optional arguments to override default model configuration.

        Returns:
            BaseChatModel instance.

        Raises:
            ValueError: If model_name is not found in LLMS.
        """
        model_entry = next((e for e in cls.LLMS if e["name"] == model_name), None)

        if not model_entry:
            available = ", ".join(e["name"] for e in cls.LLMS)
            raise ValueError(f"model '{model_name}' not found in registry. available models: {available}")

        if kwargs:
            # Take the model id from the entry rather than reusing the registry
            # name, so a name that ever diverges from its model can't send an
            # unknown id to the API.
            base_llm = cast(ChatOpenAI, model_entry["llm"])
            logger.debug(
                "creating_llm_with_custom_args",
                model_name=model_name,
                model=base_llm.model_name,
                custom_args=list(kwargs.keys()),
            )
            # ponytail: carries the token limit but not per-entry `reasoning`;
            # add that here if a caller ever needs to override a reasoning model.
            return ChatOpenAI(
                model=base_llm.model_name,
                api_key=_API_KEY,
                base_url=settings.OPENAI_BASE_URL,
                temperature=settings.DEFAULT_LLM_TEMPERATURE,
                timeout=settings.LLM_REQUEST_TIMEOUT,
                extra_body={"max_tokens": settings.MAX_TOKENS},
                **kwargs,
            )

        logger.debug("using_default_llm_instance", model_name=model_name)
        return model_entry["llm"]

    @classmethod
    def get_all_names(cls) -> List[str]:
        """Return all registered model names in order.

        Returns:
            List of model name strings.
        """
        return [e["name"] for e in cls.LLMS]

    @classmethod
    def get_model_at_index(cls, index: int) -> Dict[str, Any]:
        """Return the model entry at a specific index, wrapping to 0 if out of range.

        Args:
            index: Index into LLMS.

        Returns:
            Model entry dict.
        """
        if 0 <= index < len(cls.LLMS):
            return cls.LLMS[index]
        return cls.LLMS[0]
