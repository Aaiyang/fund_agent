# Configuration

All configuration is read from environment variables. Use `.env.development`, `.env.staging`, or `.env.production` — the app loads the right file based on the `APP_ENV` variable.

Copy `.env.example` to get started:

```bash
cp .env.example .env.development
```

---

## Application

| Variable | Default | Description |
| --- | --- | --- |
| `APP_ENV` | `development` | Environment: `development`, `staging`, `production`, `test` |
| `PROJECT_NAME` | `Fund Agent` | Displayed in API docs and logs |
| `VERSION` | `1.0.0` | API version |
| `DEBUG` | `false` | Enables debug logging and profiling middleware |
| `API_V1_STR` | `/api/v1` | API prefix |
| `ALLOWED_ORIGINS` | `*` | Comma-separated CORS origins |

---

## LLM

| Variable | Default | Required | Description |
| --- | --- | --- | --- |
| `OPENAI_API_KEY` | — | Yes | OpenAI API key |
| `DEFAULT_LLM_MODEL` | `gpt-5-mini` | No | Starting model — see [LLM Service](llm-service.md) for fallback order |
| `DEFAULT_LLM_TEMPERATURE` | `0.2` | No | Temperature for chat completions |
| `MAX_TOKENS` | `2000` | No | Max tokens per LLM response |
| `MAX_LLM_CALL_RETRIES` | `3` | No | Retries per model before switching to fallback |
| `FUND_LLM_TIMEOUT_SECONDS` | `120` | No | Initial-progress / HTTP timeout; overridden by `FUND_LLM_REQUEST_TIMEOUT_SECONDS` |
| `FUND_LLM_STREAM_IDLE_TIMEOUT_SECONDS` | `60` | No | Max gap between meaningful stream chunks after output starts |
| `FUND_LLM_TOTAL_TIMEOUT_SECONDS` | `300` | No | Hard cap per LLM call, including retries and fallback; overrides legacy `LLM_TOTAL_TIMEOUT` |
| `SESSION_NAMING_ENABLED` | `true` | No | Auto-generate a session title from the user's first message using an LLM background task |

---

## Long-term memory

| Variable | Default | Description |
| --- | --- | --- |
| `LONG_TERM_MEMORY_COLLECTION_NAME` | `longterm_memory` | pgvector collection name |
| `LONG_TERM_MEMORY_MODEL` | `gpt-5-nano` | LLM used by mem0 to extract memories |
| `LONG_TERM_MEMORY_EMBEDDER_MODEL` | `text-embedding-3-small` | Embedding model for semantic search |

---

## Database

| Variable | Default | Description |
| --- | --- | --- |
| `POSTGRES_HOST` | `localhost` | PostgreSQL host |
| `POSTGRES_PORT` | `5432` | PostgreSQL port |
| `POSTGRES_DB` | `food_order_db` | Database name |
| `POSTGRES_USER` | `postgres` | Database user |
| `POSTGRES_PASSWORD` | `postgres` | Database password |
| `POSTGRES_POOL_SIZE` | `20` | SQLAlchemy connection pool size |
| `POSTGRES_MAX_OVERFLOW` | `10` | Max overflow connections above pool size |

---

## Auth

| Variable | Default | Required | Description |
| --- | --- | --- | --- |
| `JWT_SECRET_KEY` | — | Yes | Secret used to sign JWT tokens — use a long random string in production |
| `JWT_ALGORITHM` | `HS256` | No | JWT signing algorithm |
| `JWT_ACCESS_TOKEN_EXPIRE_DAYS` | `1` | No | Access token lifetime in days — refresh it with `POST /auth/refresh` |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | `90` | No | Refresh token lifetime; `POST /auth/logout` revokes refresh tokens issued earlier |

---

## Cache (Valkey/Redis — optional)

When `VALKEY_HOST` is set, the app uses Valkey/Redis for memory search caching and rate limiting. When absent, it falls back to an in-memory TTL cache (not shared across instances).

| Variable | Default | Description |
| --- | --- | --- |
| `VALKEY_HOST` | `` (disabled) | Valkey/Redis host — leave empty to use in-memory fallback |
| `VALKEY_PORT` | `6379` | Port |
| `VALKEY_DB` | `0` | Database index |
| `VALKEY_PASSWORD` | `` | Password (if required) |
| `VALKEY_MAX_CONNECTIONS` | `20` | Connection pool size |
| `CACHE_TTL_SECONDS` | `60` | TTL for cached memory search results |

---

## Observability (Langfuse)

| Variable | Default | Description |
| --- | --- | --- |
| `LANGFUSE_TRACING_ENABLED` | `true` | Set to `false` to disable tracing entirely |
| `LANGFUSE_PUBLIC_KEY` | — | Langfuse project public key |
| `LANGFUSE_SECRET_KEY` | — | Langfuse project secret key |
| `LANGFUSE_HOST` | `https://cloud.langfuse.com` | Langfuse host (self-hosted or cloud) |

---

## Rate limiting

| Variable | Default | Description |
| --- | --- | --- |
| `RATE_LIMIT_DEFAULT` | `200 per day, 50 per hour` | Fallback limit |
| `RATE_LIMIT_CHAT` | `30 per minute` | POST /chat |
| `RATE_LIMIT_CHAT_STREAM` | `20 per minute` | POST /chat/stream |
| `RATE_LIMIT_MESSAGES` | `50 per minute` | GET/DELETE /messages |
| `RATE_LIMIT_LOGIN` | `20 per minute` | POST /auth/login |
| `RATE_LIMIT_REGISTER` | `10 per hour` | POST /auth/register |

When Valkey is configured, rate limiting is shared across all app instances. Without it, limits are per-process.

---

## Profiling (debug only)

Only active when `DEBUG=true`. Profiles every request and saves a JSON report when the request exceeds the threshold.

| Variable | Default | Description |
| --- | --- | --- |
| `PROFILING_DIR` | `/tmp/fastapi_profiles` | Directory for profile JSON files |
| `PROFILING_THRESHOLD_SECONDS` | `2.0` | Minimum wall time to trigger saving a profile. Set to `0` to profile every request. |

---

## Logging

| Variable | Default (dev) | Default (prod) | Description |
| --- | --- | --- | --- |
| `LOG_LEVEL` | `DEBUG` | `WARNING` | Log level |
| `LOG_FORMAT` | `console` | `json` | `console` for coloured dev output, `json` for structured production logs |

---

## Fund domain (AKShare, imports, background jobs)

Fund facts are collected by a `FundDataProvider` and stored in PostgreSQL; the
screenshot import pipeline runs in a Taskiq worker. Every value below is read
through `os.getenv`, so third-party limits stay tunable without code changes
(MVP spec 7.6, 7.7, 3.7.2).

| Variable | Default | Description |
| --- | --- | --- |
| `AKSHARE_MAX_CONCURRENCY` | `5` | Concurrent provider calls (semaphore) |
| `AKSHARE_TIMEOUT_SECONDS` | `20` | Per-call timeout for a blocking AKShare call |
| `AKSHARE_MAX_RETRIES` | `2` | tenacity retries per call |
| `AKSHARE_MIN_INTERVAL_SECONDS` | `0.2` | Minimum spacing between calls (throttle) |
| `FUND_NAV_STALE_HOURS` | `24` | Age after which a stored NAV counts as stale |
| `FUND_NAV_REFRESH_COOLDOWN_SECONDS` | `120` | Per-user gap between on-demand NAV refreshes (opening 持仓) |
| `FUND_NAV_REFRESH_TIMEOUT_SECONDS` | `15` | How long such a refresh may wait on the batched quote table |
| `FUND_BUSINESS_TZ` | `Asia/Shanghai` | Calendar used for `trade_date` and holding days |
| `FUND_HOT_SYNC_ENABLED` | `false` | Periodically enqueue a Hot Fund sweep from the API process |
| `FUND_HOT_SYNC_INTERVAL_MINUTES` | `360` | Interval of that sweep |
| `HOLDING_IMPORT_MAX_IMAGES` | `5` | Screenshots per batch |
| `HOLDING_IMPORT_MAX_IMAGE_MB` | `8` | Per-file upload limit |
| `HOLDING_IMPORT_TEMP_DIR` | `.runtime/holding_imports` | Where originals live until deleted |
| `HOLDING_IMPORT_STALE_MINUTES` | `30` | Reap batches stuck in `PARSING` |
| `TASKIQ_REDIS_URL` | `` | Broker URL; empty reuses `VALKEY_*`, and no Valkey means in-process execution |
| `BACKGROUND_TASK_MAX_ATTEMPTS` | `3` | Total attempts (first try + retries) for a durable job |

The hot-cache TTL for latest NAV and search results is not an env var: it is
`_LATEST_NAV_CACHE_TTL_SECONDS` / `_SEARCH_CACHE_TTL_SECONDS` in
`app/services/fund_service.py` (300s).

Screenshot recognition has no settings at all: it runs locally, PP-OCR models on
ONNX Runtime, installed with `uv sync --extra ocr`. Without that extra a batch
fails as `PARSE_FAILED` carrying `ocr_runtime_not_installed` — it does not
silently import nothing, and no image is ever sent to a third party.
