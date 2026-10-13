# Governed mem0 semantic memory

Backend migration e72a6d8f9103, prompt fund-agent-v13. Keep locked mem0 1.0 + pgvector. Confirmed profiles remain in the separate human-review workflow. Frontend/mobile memory management panels are not included.

## Ownership and scope

memory_fact owns current content, evidence, version, expiry and deletion; memory_account owns control/version/sequence; memory_write_job is a per-message durable ledger. mem0 supplies configured models, embeddings and pgvector retrieval as a rebuildable index.

Only explicit research preferences and user-described past analysis events qualify: at most five facts/message, each240 characters, content and evidence verbatim from the newest real HumanMessage. Questions, greetings, assistant/tool/image output, secrets, hypothetical examples, portfolio values and authorization instructions are excluded conservatively. Profile fields are not duplicated. Extraction sees the current delta, business date and30 recent active facts. Complex negation, mixed intent and synonym duplicates remain possible; domain evaluation and manual correction are necessary.

## Durable incremental writes

Stage before the chat LLM call, shared by normal/streamed/interrupted runs; tool loops do not re-stage accumulated history. Unique user/session/message hashes make replay idempotent while same text under a new message ID remains distinct. Commit before dispatching user_id-only Taskiq work. Broker failure leaves PENDING; an independent15-second loop recovers pending/expired-lease users. A three-second stage deadline fails without promising persistence.

PostgreSQL advisory transaction locks serialize workers per user across processes; row transactions stay short. Tenacity performs at most three persisted attempts with exponential backoff, including after restart. Defaults:90 seconds/attempt,330-second lease. FAILED tasks allow explicit owner retry with a new bounded budget and unchanged sequence. Save extraction before indexing; retry indexing without re-extracting. Stable vector IDs prevent duplicate rows on lost acknowledgements. Version guards prevent old index acknowledgements and retries overwriting newer changes to the same fact.

Successful/skipped/cancelled tasks drop text and extraction payload. Failed inputs remain until successful retry or clear/disable cancellation; automatic retention cleanup is not included. Disable stops recall/new writes and cancels old extraction generations while preserving facts for management. Disabled workers only clean deleted vectors, without starting new embeddings for retained text. Enable reindexes. Clear immediately erases application content/evidence/job inputs, increments generation and cancels old extraction. Hashed replay tombstones prevent resurrection. Vector deletion is asynchronous via retryable SYNC tasks; DB validation blocks recall immediately. Clear does not erase holdings, profiles, checkpoints, external logs/backups or already-issued model requests.

## Recall and context

Greetings, pure calendar and live NAV/quote queries skip recall. Other memory/analysis queries select up to20 candidates, default top-six and1000 estimated cl100k_base tokens. ContextManager still bounds the dynamic tail. Six-second timeout fails to empty without caching; subsequent requests can recover.

The installed pgvector score is cosine distance, lower is better: apply distance<=0.55 rather than mem0's opposite generic threshold. Reranking is disabled. Calibrate against actual embeddings and domain samples. Filter user/managed_by/generation, then verify DB ownership, ACTIVE/READY, version and expiry. Use current database content rather than stale vector text. Cache only nonempty success under user/generation/revision/query; hits still validate expiry. Changes during retrieval discard results. Analysis events expire from recall after180 days; research preferences remain until edited/deleted.

Refresh per question and after tools, including streaming and resumed runs. Put memory in the dynamic tail and leave Agent L1 memory_snapshot empty to preserve the stable system prefix. Historical memory never supplies missing confirmed profile fields or tool authorization.

## Owner management API

Prefix /api/v1/agent/memories. All routes use authenticated identity, reject user_id overrides and apply Agent rate limits. Missing/other-owner resources404, stale versions409, invalid scope/schema422, unavailable DB503.

| Method/path | Request/behavior |
| --- | --- |
| GET root | Up to100 active/unexpired facts and evidence |
| GET /settings | enabled, revision, generation, globally_enabled |
| PATCH /settings | `{"expected_revision":0,"enabled":false}` |
| PATCH /{id} | Direct correction `{"expected_version":1,"content":"比较基金时优先看费用"}`,204 |
| DELETE /{id} | `{"expected_version":1}`,204 |
| DELETE root | Clear `{"expected_revision":0}` |
| GET /jobs | Recent jobs, limit1–100; no input text/provider details |
| POST /jobs/{id}/retry | Explicit eligible failed-work retry |

Re-read settings/items after editing; indexing also increments revision. Corrections use submitted content without model interpretation.

## Deployment and compatibility

Legacy mem0 records lack source/version governance and are excluded, not automatically imported or deleted. Recall requires managed_by=fund_agent_memory_v2 and a matching DB fact. Legacy vectors/SQLite history need separate reviewed migration/cleanup. New indexing bypasses native mem0 history writes so deletion does not retain new raw content in SQLite. Installed AsyncMemory.search calls a missing filter method; the adapter composes mem0 embeddings with native pgvector search, preserving user/generation filters. Shutdown explicitly closes primary/auxiliary pools and clients. Rerun SDK adapter contracts before upgrading.

Apply Alembic upgrade head; restart API and Redis-backed Taskiq worker including app.workers.memory_write (Makefile updated). In-process fallback recovers from DB after restart; production should use Redis and an independent worker. LONG_TERM_MEMORY_ENABLED=false stops recall/worker but management can still erase/suppress DB content; physical vector cleanup waits until enabled.

See backend/.env.example for deadlines/limits/recovery configuration. Extraction output defaults to8192 tokens independently of chat limits, avoiding multi-fact JSON truncation. Vector SQL uses a two-second statement timeout, one-second lock timeout and five-second connection timeout. Already-issued index mutations finish before cancellation releases the worker lock, preventing late old writes. Extraction uses platform memory credentials rather than the chat user's LLM profile. Langfuse generation excludes input/output and sanitizes model/validation failure classes. Prometheus tracks job/retrieval outcomes, latency and rejected candidates without text/user labels. Dedicated alerts and automatic retention cleanup are not configured.

Tests cover policy, authenticated identity, distance direction, budgets, failure recovery, query refresh, idempotent indexing and owner APIs. Opt-in PostgreSQL tests (FUND_TEST_POSTGRES=true, tests/test_semantic_memory_postgres.py) cover corrections, clear/replay, leases, finite retries, advisory locks and native pgvector insert/update/distance-search/delete; fixture data rolls back and temporary vectors are deleted. External models/embeddings are mocked; actual extraction and retrieval quality require continued evaluation.
