# Market events and private portfolio links

Tool version `v9`, prompt `fund-agent-v13`. get_market_events belongs to market; identify_event_portfolio_links belongs to portfolio. Restart the backend; no migration, extra LLM call or holdings mutation is needed. Both normal and streaming paths share registration.

## Public events

Code requests [CLS telegraph](https://www.cls.cn/telegraph) with fixed parameters and a public signature following [AKShare's original implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_info.py). No search engine or arbitrary URL is accepted. Network faults use two Tenacity attempts with exponential backoff.

Parameters: scope all/macro/industry/market (default all), lookback_hours1–168 (default24), optional keyword1–80 characters (local filtering), important_only defaulttrue (publisher A/B priority), limit1–30 (default20), refresh defaultfalse (allows complete successful cache younger than60 seconds).

At most five20-item pages are scanned. requested_from/to describe the filter; coverage_from/to describe the actual publication window, potentially much shorter. A single source and bounded window cannot establish all-day/global/complete coverage. Second-based pagination may miss boundary items. page_limit_reached, partial, invalid_count, scanned_count and truncated expose limitations.

Events retain ID, URL, title, at most240 excerpt characters, Asia/Shanghai publication time, priority and rule-based categories/topics/factors. A/B is publisher priority rather than objective importance. Rules yield research hints, not verified facts; publication time differs from occurrence/effective dates. as_of uses the earliest returned publication, retaining individual dates and original fetched_at. Only complete successful windows are cached for60 seconds. No matches do not imply no events. Holidays exclusively use get_calendar.

## Authenticated holdings

Pass1–5 event_ids returned by the public tool. Optional account_id must belong to the caller; otherwise all caller accounts are considered. position_limit defaults to20 and permits up to50 holdings rows sorted by local market value.

Public snapshot references and content fingerprints expire after12 hours. Cache failures have a bounded1000-entry process fallback. Missing/expired/inconsistent references produce EVENT_NOT_AVAILABLE. Arbitrary text, URLs and user IDs are forbidden.

Runtime identity scopes holdings and enforces account ownership. Public news requests contain no identity, holdings, amounts or keywords. Fund metadata requests send only public fund codes. Private results are not cached or persisted; holdings are reread and holdings_checked_at recorded.

Evidence distinguishes disclosed_industry (historical industry-name match with industry and date), fund_name_hint (unverified name cue), macro_context (macro background with no verified sensitivity), and market_context (background without verified region/benchmark alignment). Broad industries are not forced into narrow themes. No stock look-through or complete duration/currency/geography analysis is implemented.

At most50 associations are returned, retaining total associations, holdings checked/skipped, unavailable funds and truncation. Missing evidence/no match is not proof of no effect. impact_direction is always unknown, with no causal, directional, return or trading recommendation claim.

## Verification

tests/test_market_events.py covers provenance, requests/pagination/failures, rules, cache/reference consistency and expiry, account/user isolation, no private caching, missing evidence and truncation. Both normal and streaming real Agent graphs exercise three successive chains with mocked LLM and holdings; this does not establish production database integration or real-model adherence rates.

A development smoke fetched100 valid records spanning roughly two hours. Answers must use each response's actual window rather than claim all-day coverage.
