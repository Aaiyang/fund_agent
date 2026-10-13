# Today's major-index snapshot tool

`get_realtime_market` lives in `app/agent/tools/market`, alongside the daily-close `get_market_context`. Current tool version is `v9`; prompt version is `fund-agent-v13`. Fund-specific sector queries are documented in FUND_SECTORS.md. Restart the backend to load registration and prompts. No migration is needed; normal and streaming Agent paths share the tool.

## Scope and contract

Reuse the existing public Tencent batch quote adapter, with bounded HTTP timeouts and tenacity exponential retry. Querying current quotes never falls back to the historical-close database or web search.

The fixed mainland catalog covers Shanghai Composite, Shenzhen Component, CSI300, ChiNext, SSE50, CSI500, CSI1000, STAR50, ChiNext50, SME100, SSE Dividend, CSI A100, CSI All Share and BSE50. It excludes overseas indices, stock breadth and capital flows. Overlapping index turnover cannot be summed into market-wide turnover.

Optional `index_codes` selects 1–14 catalog codes; omission selects all14. Duplicates are removed; schema and service validate the whitelist before any network query. Stocks and URLs are rejected. Default `refresh=true` fetches online; false may reuse a complete successful snapshot for15 seconds.

Per-index fields include point value, point change, percent change, previous close, open/high/low, turnover, source timestamp, date and freshness. Percent change is in percentage points; turnover is CNY. Missing values remain unknown; invalid point values appear in missing_indexes. Failed, incomplete or stale responses are not newly cached. Cache failure does not block live fetching.

Quote timestamps are explicitly Asia/Shanghai; fetched_at is separately stored as naive UTC with an explicit timezone label. Cache hits retain the original fetch time. The outer as_of uses the oldest verifiable quote; each item retains its own timestamp.

Freshness distinguishes same_day, delayed, previous_session, unknown_time and future_time. Clock-based continuous sessions use a180-second tolerance. Lunch and after-close checks use the preceding session endpoint, avoiding false staleness for normally paused updates. These clock checks do not verify exchange holidays or establish actual opening. Public snapshots may be delayed and do not guarantee exchange-grade realtime service.

## Verification

`tests/test_realtime_market.py` covers timestamps, invalid numbers, partial results, units, caching, refresh, rollover, no historical fallback, batched HTTP decoding, input limits, normal/streaming multi-turn graph refresh and same-turn loop prevention. Synthetic tests verify contracts; external smoke checks verify momentary provider access rather than ongoing availability.
