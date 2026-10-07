"""KV Cache / Prompt Cache 策略：使用率阈值、压缩标记与前缀指纹.

设计原则（任务书 §3）：稳定内容靠前，动态内容靠后；未达阈值 append-only，
达到阈值先标记 should_compact（批量压缩在 Phase 2）。
"""

import hashlib
import json


class CachePolicy:
    """缓存策略常量与计算."""

    COMPACT_THRESHOLD = 0.80

    def usage_ratio(self, total_tokens: int, max_tokens: int) -> float:
        """上下文使用率（0.0 ~ 1.0+），预算为 0 时返回 0."""
        if max_tokens <= 0:
            return 0.0
        return total_tokens / max_tokens

    def should_compact(self, total_tokens: int, max_tokens: int) -> bool:
        """使用率达到压缩阈值时标记 True（第一版只标记，不执行摘要）."""
        return self.usage_ratio(total_tokens, max_tokens) >= self.COMPACT_THRESHOLD

    def fingerprint(self, data: object) -> str:
        """Canonical JSON 的 SHA256 指纹（sort_keys + 紧凑分隔符）."""
        canonical = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


cache_policy = CachePolicy()
