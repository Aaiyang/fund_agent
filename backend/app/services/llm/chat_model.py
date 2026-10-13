"""保留兼容供应商的推理进度，不保留或发送隐藏推理正文."""

from typing import override

from langchain_core.outputs import ChatGenerationChunk
from langchain_openai import ChatOpenAI


class ProgressChatOpenAI(ChatOpenAI):
    """让超时观察器识别 GLM 等供应商的 reasoning_content 流式进度."""

    @override
    def _convert_chunk_to_generation_chunk(
        self, chunk: dict, default_chunk_class: type, base_generation_info: dict | None
    ) -> ChatGenerationChunk | None:
        """复用标准解析，只在元数据中保留有效推理片段长度."""
        generation = super()._convert_chunk_to_generation_chunk(chunk, default_chunk_class, base_generation_info)
        if generation is None:
            return None
        choices = chunk.get("choices") or chunk.get("chunk", {}).get("choices") or []
        delta = (choices[0].get("delta") or {}) if choices else {}
        reasoning = delta.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning:
            generation.message.response_metadata["fund_reasoning_chars"] = len(reasoning)
        return generation
