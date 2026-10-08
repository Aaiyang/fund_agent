"""人工复核快照的指纹：排除动态基金候选和抓取时间，覆盖所有待应用字段."""

import hashlib
import json

from app.schemas.holding_import import ImportDetail


def holding_review_digest(detail: ImportDetail) -> str:
    """草稿、裁决或当前持仓版本变化后必须重新向用户展示并确认."""
    payload = {
        "id": detail.id,
        "account_id": detail.account_id,
        "items": [item.model_dump(mode="json", exclude={"candidates"}) for item in detail.items],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
