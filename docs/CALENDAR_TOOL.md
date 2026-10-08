# Online holiday calendar tool

The default Agent tool set includes `get_calendar`, which retrieves mainland China's civil holiday and makeup workday schedule. Users can ask about today, a specific date, a date range, or a year's holiday schedule in chat. No API key or database migration is required.

| Arguments | Coverage |
| --- | --- |
| `{}` | Today in `FUND_BUSINESS_TZ` (default Asia/Shanghai) |
| `{"start_date":"2026-10-10"}` | One date |
| `{"start_date":"2026-10-01","end_date":"2026-10-12"}` | Inclusive range, at most 31 days, including cross-year ranges |
| `{"year":2026}` | Holiday and makeup workday entries only |

Dates must use `YYYY-MM-DD`. Do not combine `year` with date arguments. Supported request years are 2000–2100, subject to upstream availability. An unpublished or unavailable year returns `DATA_NOT_AVAILABLE`, rather than inferring holidays from weekdays.

Day kinds are `holiday`, `makeup_workday`, `weekend`, and `workday`. Special arrangements override weekday rules. A Saturday makeup day has both `is_weekend=true` and `is_workday=true`. **Civil workdays are not securities trading days**; consult exchange or fund announcements separately.

## Source and freshness

The default source is the third-party [Timor holiday API](https://timor.tech/api/holiday/), queried through `/year/{year}/`. It is not an official government feed. Official notices take precedence, such as the [2026 State Council holiday notice](https://www.beijing.gov.cn/cs/gncs/zcwj/202603/t20260327_4568275.html). No annual calendar is hardcoded.

- Default `refresh=true` fetches online each time. Both years must succeed for a cross-year result.
- `refresh=false` may reuse a successful snapshot fetched within five minutes; older snapshots trigger an online refresh.
- Only validated successful snapshots are cached, for at most six hours. Tenacity allows two HTTP attempts with exponential backoff for transport failures, HTTP 429, and 5xx. Missing years and malformed payloads are not immediately retried.
- On upstream failure, a snapshot less than six hours old can be returned with `stale=true`, its original fetch timestamp, and a warning. Without a valid snapshot the tool returns an error.
- Results include `sources`, `fetched_at_utc`, and `cache_used`. The UTC timestamp is when this system fetched the data, not the official publication or upstream modification time. Cross-year results report the older fetch time. The tool envelope's `as_of` is the requested end date.

Validation rejects empty years, mismatched date keys/years, invalid booleans, and years missing New Year's Day or National Day. These checks do not prove that the upstream data contains every holiday or adjustment. Third-party availability and rate limits still apply. A compatible self-hosted or supported provider can be configured for enterprise use.

## Configuration and implementation

```dotenv
FUND_HOLIDAY_API_BASE_URL=https://timor.tech/api/holiday
FUND_HOLIDAY_API_TIMEOUT_SECONDS=8
```

Only server configuration controls the URL; the model cannot supply one. Requests contain no user credentials or chat content. Existing runtime trading-session hints now explicitly describe their weekday/clock estimate and require a calendar lookup for holiday questions. This tool does not establish whether an exchange is open.

Implementation lives in `app/integrations/holiday_calendar.py`, `app/services/calendar_service.py`, and `app/agent/tools/get_calendar.py`. Tool set version is `v2` and system prompt version is `fund-agent-v3`. Restart the backend to load the new tool.

`tests/test_calendar_tool.py` covers date validation, day classification, cross-year/year queries, cache expiry, unavailable years, malformed upstream responses, HTTP retry policy, and actual LangGraph tool execution. Tests use fake data and do not call a real LLM or depend on the public endpoint.

Verification on 2026-10-08: the full backend suite passed with 434 passed and 2 skipped; Ruff and Pyright passed. A separate live check returned 39 special dates for 2026, correctly classified October 10 as a Saturday makeup workday, and produced about 1,878 tokens for the annual tool result. The 2027 response was empty and reported as unavailable. Live findings are a dated snapshot and should be refreshed for later use.
