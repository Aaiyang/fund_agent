# mem0 and database user profiles

mem0 + pgvector retains semantic memories. PostgreSQL owns explicitly confirmed profile fields; existing memories are not automatically promoted. This release implements backend APIs and Agent integration. Frontend/mobile management panels are not included.

## Data boundaries

`user_persona` stores confirmed fields, a monotonic revision and per-field provenance. `user_persona_proposal` holds pending changes and evidence from the actual current user message. `user_persona_history` records committed changes. Current holdings, transactions, NAV and returns remain in business tools.

Allowed fields: `response_language` (zh-CN/en), `response_detail` (concise/balanced/detailed), `investment_experience` (beginner/intermediate/experienced), `risk_preference` (conservative/balanced/aggressive), `investment_horizon_months` (strict integer 1–600), `investment_goals` (up to five strings of 1–120 characters), `excluded_fund_types` (equity/bond/money_market/mixed/index/qdii/fof/reit/commodity).

Omitted fields remain unchanged; explicit null deletes a field. Unknown fields, identities and holdings are rejected with 422. Free text is data, not a new instruction. These declarations are not a formal risk assessment or transaction authorization. Goals and horizon are user-wide in this version; ambiguous references to separate funds require clarification.

## API

Base path: `/api/v1/agent/user-profile`, no trailing slash. All routes are rate limited and authenticated with user/session access tokens. Refresh tokens are rejected. Ownership is never a client-selected argument.

| Method / suffix | Behavior |
| --- | --- |
| GET base path | revision, fields, provenance, pending_proposals; unknown fields are null |
| PATCH base path | `{"expected_revision":0,"changes":{"response_detail":"concise"}}` |
| DELETE base path | `{"expected_revision":1}`; delete fields, proposals, evidence and history, retain an empty row with increased revision |
| GET `/history?limit=20` | Committed changes, newest first; limit 1–100 |
| POST `/proposals/{id}/decision` | `{"expected_revision":0,"decision":"accept"}` or reject |

Stale changes return 409; another user's proposal returns 404. Repeating a completed decision does not increase revision or duplicate history. Terminal decisions cannot be reversed. Editing or accepting supersedes other pending proposals. Rejecting does not advance revision. Users can have at most 20 pending proposals; identical changes from the same message/version reuse the record.

## Agent behavior

`propose_user_profile_update(changes, evidence)` creates a pending proposal when the user explicitly requests a lasting preference or correction. Trusted runtime supplies user/session and latest HumanMessage ID. Evidence must be a verbatim substring of that message, at most 500 characters. Assistant, tool, screenshot and older messages cannot be evidence.

The tool never confirms or erases a profile; ordinary chat approval cannot apply changes. Clients retrieve pending_proposals, show evidence and proposed changes, and call the separate human decision API.

Every chat node reads confirmed fields into the dynamic context tail, covering streaming, non-streaming and resumed runs. Pending proposals, raw evidence and audit records are excluded. Existing mem0 session snapshots retain their behavior. Missing fields remain unknown; database failures produce an explicit unavailable marker. A current user correction takes priority over old profile data.

Evidence checks prove origin, not correctness. Human review must check assumptions, negation and scope. Clearing a profile does not erase mem0 memories or checkpoints, or revoke in-flight LLM requests. Stale edits/confirmations cannot restore erased fields.

## Deployment

Apply migration `d31f9a6b8204` with `alembic upgrade head`, then restart the backend. USER_PERSONA_ENABLED=true by default enables automatic injection; false leaves management APIs available. Tool version v4; system prompt fund-agent-v6.

The existing LangGraph/Langfuse pipeline selects proposals without an additional extraction LLM. Unit/API/Graph tests cover validation, authentication, evidence and graceful degradation. Opt-in PostgreSQL tests (`FUND_TEST_POSTGRES=true`, tests/test_user_persona_postgres.py) cover isolation, idempotence, version conflicts, erasure and rollback. Temporary data is rolled back.

Existing mem0 behavior is preserved. Incremental extraction, durable memory jobs and query-specific recall remain separate follow-up work.
