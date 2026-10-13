# Fund sector evidence and live sector quotes

`get_fund_sectors` and `get_sector_market` are both registered in the `fund` group. Current tool version: `v9`; prompt: `fund-agent-v13`. Restart the backend; no migration is needed. Both normal and streaming Agent paths use the registration.

Resolve a fund name with `search_funds`, query its six-digit code with `get_fund_sectors`, then query each returned `BK` code with `get_sector_market`. Direct sector name queries are also supported. Each tool returns at most five entries. Quote queries accept `industry`, `concept` or `all`; `refresh=true` is the default.

## Evidence boundaries

FundService provides the fund name/type from the fund repository or existing profile provider, plus the latest disclosed industry allocation. This query does not fetch historical NAV or stock prices.

- `disclosed_industry` means exact normalized name matching between a disclosed industry and the industry quote directory. Its weight is percentage points of fund NAV at the disclosure date.
- `fund_name_hint` is an unverified theme inferred from the fund name, without a weight or asserted benchmark relationship.
- Broad regulatory industries are never forcibly mapped into narrower quote sectors. Unmatched industries and missing evidence remain explicit. Multiple sectors are allowed; generic investment styles are excluded.
- Mainland A-share sectors only: overseas, bond, money-market and other unsupported funds do not receive forced associations. This is conservative evidence matching, not a complete holdings classification. More detailed attribution requires stock classification and comprehensive holdings evidence.

Sector returns never imply fund returns or an intraday NAV estimate.

## Provider, caching and freshness

The async adapter uses fixed Eastmoney public endpoints following the primary [AKShare industry implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_board_industry_em.py) and [concept implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_board_concept_em.py). Tenacity bounds exponential retries and switches to a fixed same-provider backup host on network failure. HTTP timeout is eight seconds; concurrency is four. User input cannot become a URL or arbitrary secid.

Catalogs use stable code ordering, up to twenty pages of 100 entries. Only complete catalogs are cached for 24 hours; duplicate/missing pages or changing totals fail. Industry/concept catalogs degrade independently and expose `unavailable_catalogs` rather than falsely establishing absence.

Quotes refresh online by default. Optional successful quote caching lasts fifteen seconds, revalidates source time and excludes errors, missing percentages, stale/invalid quotes. Partial failures remain per-entry errors. Historical closes never replace current quotes.

Prices and point changes use the provider's `f59` decimal precision. Percent changes divide the integer field by 100: -1.11 means -1.11%. `f86` supplies quote time in Asia/Shanghai; fetch time is separately UTC. Global `as_of` uses the oldest verifiable quote time. Shared index freshness validation exposes same_day, delayed, previous_session, unknown_time or future_time. Clock-based checks do not establish exchange opening or holiday status. Public snapshots may be delayed; null is unknown, never zero.

`tests/test_sector_tools.py` verifies evidence, unsupported markets, pagination, units/times, bounded inputs, failure/cache behavior, and normal/streaming Agent tool chaining and refreshes. Scripted model tests establish execution behavior, not real-model adherence. The existing placeholder related-sectors API and frontend views are outside this tool change.
