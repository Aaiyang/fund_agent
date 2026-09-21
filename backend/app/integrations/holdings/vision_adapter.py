"""Vision/OCR adapter: OpenAI-compatible chat vision API for screenshots.

The adapter is swappable (MVP spec 3.7.2) — any OpenAI-compatible vision
endpoint works by changing VISION_* settings. It understands the image and
returns structured rows; no OCR SDK is wired into business code.
"""

import base64
import json
from pathlib import Path

from openai import AsyncOpenAI
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings
from app.core.logging import logger

_EXTRACT_PROMPT = """你是基金持仓截图解析器。请从这张手机基金 App 持仓截图中提取所有基金持仓条目。

对每个基金条目返回以下 JSON 字段（无法识别或不存在时设为 null）：
- fund_name: 基金名称（可能带后缀如 "混合C"，保留原文）
- fund_code: 基金代码（6位数字，截图中存在时）
- market_value: 持有金额/当前市值（数字，去掉货币符号和千分位）
- shares: 持有份额（数字）
- cost_amount: 持仓成本金额（数字，若有）
- average_cost_nav: 平均成本单价/成本净值（数字，若有）
- profit_loss: 持有收益/累计收益（数字，亏损为负）
- profit_loss_rate: 持有收益率（百分数数字，如 -13.46 表示 -13.46%）
- daily_profit_loss: 当日收益（数字，若有）
- data_date: 截图中的数据日期（YYYY-MM-DD，若有）
- confidence: 该条目识别置信度 0.0-1.0

仅返回一个 JSON 数组，每个元素对应一个基金条目。不要输出任何其他文字、解释或 markdown 代码块标记。"""


class VisionAdapter:
    """Calls an OpenAI-compatible vision model to extract holdings rows."""

    def __init__(self) -> None:
        """Initialize with a lazily-created API client."""
        self._client: AsyncOpenAI | None = None

    def _get_client(self) -> AsyncOpenAI:
        """Lazily create the API client (keys may be configured later)."""
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=settings.VISION_API_KEY or "missing",
                base_url=settings.VISION_BASE_URL,
                timeout=settings.VISION_TIMEOUT_SECONDS,
            )
        return self._client

    @property
    def available(self) -> bool:
        """Whether vision extraction is configured and enabled."""
        return settings.VISION_ENABLED and bool(settings.VISION_API_KEY)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=8),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        before_sleep=before_sleep_log(logger, 30),
        reraise=True,
    )
    async def extract_positions(self, image_path: str) -> list[dict]:
        """Extract raw position dicts from one screenshot.

        Raises:
            RuntimeError: When the model is unconfigured or returns unusable output.
        """
        if not self.available:
            raise RuntimeError("vision_adapter_not_configured")

        image_bytes = Path(image_path).read_bytes()
        encoded = base64.b64encode(image_bytes).decode()
        # Sniff content type from magic bytes; default to png
        suffix = Path(image_path).suffix.lower()
        mime = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }.get(suffix, "image/png")

        response = await self._get_client().chat.completions.create(
            model=settings.VISION_MODEL,
            max_tokens=settings.VISION_MAX_TOKENS,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _EXTRACT_PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
                    ],
                }
            ],
        )
        content = response.choices[0].message.content or ""
        rows = self._parse_rows(content)
        logger.info("vision_extraction_completed", rows=len(rows), image=Path(image_path).name)
        return rows

    @staticmethod
    def _parse_rows(content: str) -> list[dict]:
        """Parse the model reply into row dicts, tolerating code fences."""
        text = content.strip()
        if text.startswith("```"):
            text = text.split("```")[1] if "```" in text[3:] else text[3:]
            if text.startswith("json"):
                text = text[4:]
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as e:
            # Never log reply content: it carries the user's holdings (spec 16)
            logger.warning("vision_reply_not_json", reply_chars=len(text), error=str(e))
            raise RuntimeError("vision_reply_not_json") from e
        if not isinstance(parsed, list):
            logger.warning("vision_reply_not_array")
            raise RuntimeError("vision_reply_not_array")
        return [row for row in parsed if isinstance(row, dict)]


vision_adapter = VisionAdapter()
