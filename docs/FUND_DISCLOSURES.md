# Fund manager history and disclosure tools

`get_fund_managers` and `get_fund_announcements` belong to `fund` and take a six-digit fund code. Tool version `v9`, prompt `fund-agent-v13`. Restart the backend; no migration is needed. Normal and streaming Agent paths share registration.

## Manager history

The manager tool accepts code, limit (default50, max100), and refresh (defaultfalse, up to one-hour successful cache). `periods` preserve joint management intervals, identities, start/end dates, source duration and current markers. `tenures` merge each manager's adjacent/overlapping intervals by manager ID. Reappointments separated by a gap and different managers sharing a name stay separate. Merging precedes output truncation; totals and `truncated` expose both list limits. No individual return is inferred from team performance.

Null end dates paired with `is_current=true` mean the source labels the interval ongoing. UTC `fetched_at` remains the original cache fetch time, not a business update or appointment date. The source page does not supply its business update time. Parsing selects only the fund's history table, validates code, headings, identities and dates, and excludes other funds managed by the same people. Unknown structure is an error, never empty history or a current-name fallback. Example source: [fund000001 manager history](https://fundf10.eastmoney.com/jjjl_000001.html).

## Announcements

Parameters: fund_code, category (all/reports/major_changes/personnel/dividend/operation/sales/other), optional publication start/end dates and title keyword, page (1–1000), limit (default20, max50), refresh (defaultfalse, five-minute successful cache).

The tool returns titles, publication dates, source categories, IDs and original disclosure links. `content_available=false`: report/PDF bodies have not been read. Publication is not an effective date; global `as_of` is the newest verifiable publication date in returned entries.

Major-change hints use explicit title rules for manager changes, contracts, liquidation, mergers/transformation, investment scope/strategy, names/benchmarks, management/custodian institutions, fees and subscriptions/redemptions. These are unverified candidates, neither an official exhaustive classification nor proof an event took effect. Termination of a sales agency does not mean fund liquidation.

Each call scans one page of up to50 source records before applying date/keyword/title-hint filters. `upstream_total` belongs to the upstream source category; `scanned_count` and `matched_count` cover only this page. `has_more`/`next_page` advance to the next scanned page. Increase limit to50 for the current page's remaining matches. Empty matches do not establish absence elsewhere. There is no unbounded full-history scan.

The async adapter follows the primary [AKShare announcement implementation](https://github.com/akfamily/akshare/blob/main/akshare/fund/fund_announcement_em.py), retaining real metadata. Fixed HTTPS endpoints and validated codes/IDs prevent arbitrary URL requests. Only public codes/categories/pages are sent. Timeout10seconds, concurrency4, two Tenacity attempts with exponential backoff for network errors. Parsing/identity/page failures remain errors. Failed or malformed partial pages are not cached; cache outages still permit online queries. Dates remain unknown rather than receiving today's date.

`invalid_items` counts skipped invalid records; `missing_items` counts records the source declared for this page but omitted. Partial pages are explicitly warned and never cached.

`tests/test_fund_disclosures.py` covers history merging and identity, disclosure category/date/link boundaries, hint classification, page limits, safe failure/success caching, and normal/streaming Agent execution across new turns. Scripted-model tests are execution checks, not real-model adherence evaluations. Public-source coverage is not an all-channel completeness guarantee.
