# Write and execution safety

Portfolio writes use the shared async database transaction. The account row is
locked before planning a trade, seeding an opening balance, applying a confirmed
import, or projecting the ledger. Position updates use an atomic version predicate;
an absent expected version means create-only on the public adjustment path.

`POST /api/v1/portfolio/positions/{fund_code}/trades` requires `idempotency_key`
(1–64 nonblank characters). Keep the same key and payload when retrying an uncertain
response. Reusing a key with different parameters returns HTTP 409. The request key
and parameter fingerprint are hashed into the existing first-leg transaction reference;
no database migration is needed. Replays return the current position without adding
another trade. The mobile form retains keys for unchanged submissions until success.
Older external clients must add this field before upgrading the backend.

Cache lock acquisition returns a `LockLease`; release accepts that exact lease.
Never release by key alone. Chat, human decisions, clear-history and delete-session
share the same session key. Active execution makes clear/delete return HTTP 409;
they do not cancel the active run. Execution rechecks session existence after acquiring
the lock. Multi-process deployments still require a shared Valkey/Redis backend.

Authentication and session naming now use the shared async engine. AKShare waiting
timeouts cannot release concurrency capacity while the underlying thread is still running.
Blocking providers must retain their own network timeouts. Broker logs omit credentials,
and structured log rendering redacts secret fields and URL user information.

Run `tests/test_portfolio_write_postgres.py` with `FUND_TEST_POSTGRES=true` against
an isolated PostgreSQL database with the application schema. Tests use separate
connections to check conflicts, overselling, rollback, cancellation and replay. They
create unique fixture records and clean those records on completion.
