# Agent image holdings import: backend contract

This phase implements the backend only. Both the web and mobile clients will use this contract when their image picker, progress display, and human review UI are added. Existing chat screens do not yet provide these controls.

The flow reuses the screenshot pipeline: choose an owned account, upload images, run local OCR in the existing queue, let the Agent read the draft, pause through a LangGraph interrupt, obtain a human decision, then resume the Agent. Neither upload nor an LLM tool applies holdings. Only an authenticated human decision endpoint writes the approved draft.

## Client sequence

All paths below are relative to `/api/v1` and require the current chat session access token, rather than a user or refresh token.

| Action | Endpoint | Contract |
| --- | --- | --- |
| Upload | `POST /chatbot/holding-imports/screenshots?account_id=7` | multipart `files`; 202 with `import_id`, `image_count`, `status=PARSING` |
| Progress / full draft | `GET /chatbot/holding-imports/{import_id}` | `import_batch.status` and `items` |
| Agent request | `POST /chatbot/chat` or `/chatbot/chat/stream` | user messages plus `holding_import_ids` |
| Recover pending review | `GET /chatbot/pending-action` | `pending_action`, or null |
| Human decision | `POST /chatbot/holding-imports/{import_id}/decision` | `decision`, `interrupt_id`, `review_digest` |

Default upload limits are 1–5 PNG/JPEG/WEBP images, each at most 8 MiB, using the existing holding import settings. Original images stay in temporary local storage and are not sent to the chat model as URLs or base64. A Redis broker requires the existing screenshot worker; otherwise the existing in-process broker runs the task.

Poll until `REVIEW_REQUIRED`, then send user messages with `holding_import_ids` containing IDs from upload responses. If sent earlier, the Agent reports ongoing recognition; the client must query again later. Recognition completion does not automatically wake the chat in this version. Ownership and session binding are checked before IDs enter the dynamic context.

## Tools and review UI

- `get_holding_import(import_id)` reads progress and up to 20 draft rows. The HTTP endpoint supplies the full draft.
- `request_holding_import_confirmation(import_id)` constructs a review card from actual draft data and pauses with `interrupt()`. It never calls the holdings confirmation service.

Tools accept only an import ID, never file paths, user IDs, or model-supplied position values. The review card is carried by `ChatResponse.pending_action`, `GET /messages`, and the final SSE event with `done=true`. It contains `kind=holding_import_review`, `import_id`, `account_id`, `image_count`, `interrupt_id`, `review_digest`, full `items`, and a snapshot-overwrite notice. Render the amounts, shares, fund matching, validation issues, confidence, user decisions, and existing-position comparison before enabling confirmation.

Checkpointed interrupts survive reconnects and restarts. Fetch `/pending-action` to recover them. Ordinary chat text such as “confirm” cannot approve a holding update; while a review is pending, chat returns 409 `holding_import_review_pending`.

For a human button click, POST `decision` (`confirm` or `cancel`) with the exact `interrupt_id` and `review_digest` copied from the card. The backend verifies the real pending interrupt and import ID. Success returns deterministic `import_id`, `status` (`APPLIED` / `CANCELLED`), `applied`, `skipped`, resumed `messages`, and any next `pending_action`. Use these fields rather than model-generated prose to show success.

## Corrections and recovery

Use the existing `PATCH /holding-imports/{import_id}/items/{item_id}` to edit draft rows or choose UPDATE / EDIT / SKIP. Afterwards fetch `/chatbot/pending-action` again and display the updated draft and digest. Confirmation with the old digest returns 409 `import_review_changed` without applying holdings. The digest includes all rows, decisions, and current-position comparisons, but excludes dynamic fund candidates.

Confirmation preserves snapshot semantics: update accepted funds and supplied fields within the chosen account, leave unlisted holdings intact, preserve existing purchase dates, and write IMPORT_ADJUSTMENT audit entries rather than buy/sell transactions. Positions, audit entries, account import time, and APPLIED status commit in one database transaction. Confirmation, draft editing, and cancellation lock the batch row. Repeated confirmation is idempotent. Failed transactions leave all positions/audit rows unchanged and retain images; confirmed, cancelled, and failed-recognition imports use the existing image cleanup.

Decisions and graph resumption are serialized per session. Valkey locks refuse unprotected decisions when the backend is unavailable. Single-process development uses an in-memory lock; multiple API workers require working Valkey/Redis caching. Concurrent decisions return 409 `holding_import_decision_in_progress`.

After 503 `holding_import_decision_failed_check_status` or 504 `holding_import_decision_timeout_check_status`, query the import status before retrying the same decision. Application may have committed before model resumption failed; APPLIED imports are not applied again. Cancellation of an applied import conflicts. Cross-user, cross-session, or non-chat imports return 404.

## Migration and validation

Migration `a62d8b409e15` adds nullable `holding_import.chat_session_id` and its index; existing ordinary imports remain NULL. The development database has been upgraded. Migrate other environments with Alembic and restart the backend before use. Tool set version is `v3`; system prompt version is `fund-agent-v5`.

Tests exercise actual LangGraph interruptions/resumption, streaming cards, checkpoint recovery, ownership/session isolation, stale-review rejection, plain-chat refusal, repeat/concurrent decisions, retry after resume failure, and upload validation. Separate PostgreSQL tests run inside an outer rollback transaction and verify full rollback on mid-batch failure and idempotent audit writes. No real chat model is called by these tests.

Verification on 2026-10-08: the full backend suite passed with 465 passed and 4 optional database tests skipped. The two PostgreSQL tests for this feature were enabled separately and both passed. Ruff, Pyright, and an import smoke check in the current backend environment passed. OpenAPI exposes all four new endpoints, both tools are registered, and the local OCR runtime is available. Web/mobile interaction and real-user-image chat-model behavior were not tested in this backend-only phase.
