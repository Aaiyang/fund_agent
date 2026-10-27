# Optional multi-role research

Ordinary research keeps its existing `standard` / `deep` evidence modes and defaults to
`strategy="single"`. Users can explicitly request multi-role research, or select
**多角色深度研究** below an eligible report in the mobile chat. Supported tasks are fund
research, fund comparison, portfolio diagnosis and allocation analysis. Stock and
sector research retain the existing workflow.

## Report references and session scope

Eligible new assistant messages expose `research_id`. Submit exactly one new user
message to the existing `/chatbot/chat` or `/chatbot/chat/stream` endpoint with:

```json
{
  "messages": [{"role": "user", "content": "请对这份报告进行多角色深度研究"}],
  "research_followup_id": "<32-character server-issued report ID>"
}
```

The server looks up the original request and confirmed fund objects in that session's
checkpoint. It preserves the original account/action/amount scope, creates a new turn,
and fetches current evidence. A report reference cannot change accounts or accompany
attachments. Unknown references return 404; an unfinished graph run returns 409. A
repeated request for a completed follow-up returns its saved report without new model
or tool calls. The entry is an underlined text link. Old reports without server metadata have no link; users can explicitly
request a new multi-role study with their targets.

## Roles

Roles follow professional fund-evaluation dimensions, and a dimension only exists when
the system can actually fetch data for it. Rates/fee schedules, peer rankings and
percentiles, turnover, full holdings beyond the disclosed top ten, and prospectus
investment scope are **not** available, so no role is assigned to them; asking a model
to analyse unavailable data produces confident filler, which is what this feature kept
doing.

| role | owner (signs the section) | dimension | evidence visible to it |
| --- | --- | --- | --- |
| `performance` | 业绩分析师 | 业绩与基准契合 | snapshot period returns, `get_fund_benchmark` (benchmark text, parsed weights, excess return / beta / alpha / tracking error when every component index resolves), common-window comparison, market context |
| `risk` | 风险分析师 | 风险与回撤 | NAV metrics including max drawdown **with peak/trough dates**, annualised volatility, Sharpe and Sortino (both `_rf0`: zero risk-free rate), comparison risk fields |
| `holdings` | 持仓与风格分析师 | 持仓与行业风格 | disclosed top-10 with prior-quarter weights, weight changes, new entries, industry allocation, linked sectors and board quotes |
| `manager` | 基金经理研究员 | 基金经理与团队 | manager periods, merged tenures, and the source page's 任职回报 column as raw text |
| `disclosure` | 披露与来源质量审查员 | 披露与来源质量 | announcement index (titles, dates, major-change hints only — never body text), market events |
| `portfolio` | 组合配置顾问 | 组合适配 | positions and portfolio ledger, event-position links, code-computed allocation scenarios. Created **only** when a position read was attempted, and it runs only when that read succeeded |

Both name columns come from one map (`app/agent/roles.py`: `ROLE_OWNERS` / `ROLE_LABELS`),
and the section heading the synthesizer must copy verbatim is generated there too
(`### 风险分析师｜风险与回撤`). Mobile's progress line shows the owner, not the dimension.
Owners are professional titles, never invented people: nothing behind a read-only pipeline
corresponds to a named staff member.

Slices are deliberately disjoint. A supplement therefore revises only the role whose own
data changed — for example new announcements reach `disclosure`, not `portfolio`.

## Communication protocol

The intent-specific deep chain embeds `multi_role_agents` after its deterministic evidence
and scenario nodes:

1. Code builds **one assignment per role** (never fund × role) listing the evidence that
   role must cite, persists the bounded evidence packet and the stage start time, and lets
   each role top up at most four missing calls from a fixed argument map. Assignments do
   not grow with the number of funds, because the output caps cannot absorb a task count
   that scales with them.
2. Roles run in parallel. Each returns findings that cite server-issued `evidence_id`s
   only, plus one optional `stance`: a professional position on a named topic
   (`position_size`, `benchmark_fit`, …) with the condition that would flip it. A join
   barrier waits for every envelope, including explicit skipped or failed ones.
3. The reviewer receives each role's findings, the server-derived coverage, each role's
   stance, and `cited_evidence` — bounded excerpts of only the evidence entries some finding
   actually cites. It no longer re-reads the whole packet: its job is to judge whether a
   claim is supported by what it cites, not to re-ingest the sources. Feedback points at a
   role and finding index; unknown claim targets, evidence IDs and fund codes are rejected
   and disclosed. It is told explicitly that a colleague's stance is not evidence and that
   it must not raise issues in order to manufacture a disagreement.
3a. After each role call the server runs a numeric audit: percentages, amounts and
   two-decimal numbers in a finding should be findable in the evidence it cites. The
   `numeric_audit` payload is advisory only; derived sums, rounding and unit conversions
   may miss, so it never changes coverage or run status.
3b. Only for a real contradiction about the same object and metric may the reviewer fill
   the optional challenger fields (role, finding index, evidence). The server validates the
   challenger's role slice and evidence and keeps at most two challenges. A challenge is
   delivered as `cross_examination` to the challenged role's single revision payload; it
   adds no debate node and no extra model call, and `divergences` records whether it was
   addressed.
4. At most two independent review-requested supplement calls execute in parallel, from a
   fixed read-only whitelist: announcements (10), managers (20), or market events (10 within
   168 hours). Arguments are constructed by the server and identical calls are deduplicated.
   The acquisition ledger may add up to three bounded retries for required, retryable calls
   that have not succeeded, prioritising actual failures over never-attempted calls.
5. Coverage gaps are classified by code as: evidence available but not cited, fetch failed,
   not attempted, or upstream unavailable. Only the first two trigger action. Available but
   uncited evidence goes straight to revision. Failed or missing calls are retried once;
   only usable new evidence triggers a revision. Upstream-empty or null metrics are recorded
   as gaps without a retry or revision. Review failure does not trigger a full rewrite.
   Unnecessary revisions reuse reviewed first-round work. A failed revision keeps the useful
   first-round findings while disclosing the unresolved feedback.
6. One synthesis receives the machine-checked completion matrix, the divergence list and the
   server-paired `tensions` (same topic and object, strictly opposite stances from different
   roles) and must write the report as a team document: one section per dimension under the
   code-generated owner heading, a 同事立场与分歧 section that transcribes each tension (or
   states plainly that the dimensions agree and why), an 行动建议与触发条件 table, and a
   closing 综合结论与分歧 whose every judgment names the owners supporting and opposing it
   alongside real `[ev_…]` citations. It must also include a 角色分歧与未解决项 section
   transcribing every divergence with its resolved-or-not status. Agent consensus is not
   independent factual support, and internal enum keys must not appear in the prose.

The server assigns each envelope's task ID, sender and round. The reducer merges by
`(run_id, role, round)`, sorts deterministically, accepts identical replay, and rejects
conflicting writes or mixed runs. Evidence IDs hash the turn ID and the exact bounded
evidence content. Claims referencing unavailable IDs are dropped, not repaired by
guessing. Existence checks do not prove semantic support: the reviewer performs that
assessment, and model judgments still require quality evaluation.

## Completion contract

Coverage is **derived by code from the citations**, not self-reported by the model.
`derive_coverage` first drops any finding citing an evidence ID that does not exist or is
outside that role's slice, then checks each `EvidenceRequirement` — `{label, tools, scope}`
where `scope="per_fund"` requires a matching citation for every confirmed object — against
the surviving findings' citations. A dimension is `completed` only when every requirement
is met; `partial` when some are missing; `blocked` when no finding survives.

This replaced a contract that asked the model to fill a coverage table with cross-checked
finding indices and per-tool-group object matching. Measured over 12 runs: 0 of 31 role
outputs reached `completed`, every partial had exactly the cap of 4 findings and 4 gaps,
11 of 11 final results were `partial`, and 8 of 12 reviews failed — four of them instantly
with nothing verified to review. The model is good at citing and bad at bookkeeping, so
the bookkeeping moved to code.

A `stance` is the one thing a role still self-declares, and it is deliberately inert:
`derive_coverage` may drop a stance whose own citations are unverifiable, but a stance never
enters the status expression, the coverage row or the gap list. Wiring it to any of those
would rebuild the same "always partial" gate that the coverage table created. Tensions are
paired from stances by code after the fact, so an empty tension list is a legal outcome and
no run can be failed for lacking a disagreement.

Revision feedback acknowledgement still checks presence and ownership through
`addressed_issue_indices`; out-of-range acknowledgements are dropped and reported. The
server appends a scope/coverage note using Chinese dimension labels, stating what **was**
covered and listing only the unmet items, so the synthesizer cannot silently omit
confirmed objects. Roles that never ran are excluded from the completion denominator.
Sources flagged partial or stale keep the overall result partial. Scope stays at the
existing maximum of three funds.

Follow-up memory retrieval uses the original research question. The portfolio role
receives confirmed constraints from the existing persona service and, separately,
up to 2000 characters of relevant historical statements. Truncated or unconfirmed
memory does not override the current request or confirmed profile. Every other role
receives no private profile and no private ledger.

Agent outputs are private checkpoint state. The nested graph returns only evidence,
gaps and communication results; it never returns the input chat messages. Only the
final report reaches the user as answer text. Custom SSE progress uses the separate
`research_progress` field for evidence, analysis, review, supplement, revision and
report stages. Internal model token streams are suppressed, and research chart
references still pass the existing server validation.

## Execution and limits

The parent graph's PostgreSQL saver persists the nested workflow. Existing session
locks serialize chat, continuation and deletion. After execution fails or a stream is
interrupted, the existing `/chatbot/pending-action` and `/chatbot/continue` flow resumes
unfinished checkpoints without replaying completed graph nodes. If the multi-role subgraph
already contains failed roles, continuation starts a fresh multi-role run with the same
confirmed task instead of only writing a degraded report from `write_report`. When roles
succeeded and only final synthesis failed, it resumes in place without repeating role or
evidence work. Individual role or review failures still produce a partial report if not
continued; they do not trigger an unbounded debate.

All role calls use the existing user-scoped LLM service, structured Pydantic outputs,
tenacity retry/fallback and inherited Langfuse callbacks. One-off structured calls do
not change shared tool bindings or the user's active-model index. Configure:

- `FUND_MULTI_ROLE_RESEARCH_CALL_TIMEOUT=60`: deadline for each analysis/review/revision.
- `FUND_MULTI_ROLE_RESEARCH_TOTAL_TIMEOUT=180`: total communication budget including
  supplements, persisted across resume. Initial evidence and final synthesis retain
  their existing separate deadlines. Expiry preserves available work with explicit gaps.
- `FUND_MULTI_ROLE_RESEARCH_MAX_TOKENS=8192`: output budget, bounded to 1024–65536.
  Measured over 21 role/review calls the largest output was 4262 tokens and
  `finish_reason=length` never fired, so the previous 32768 was idle headroom; this keeps
  roughly 2× because GLM counts hidden reasoning into the same budget.
- `FUND_MULTI_ROLE_RESEARCH_REASONING_EFFORT=low`: applied only to GLM-5.3 models.
  At `high` each role call took 45–85s and 27 of 77 completed calls returned
  `output_chars=0` — the whole budget went to reasoning that the interface never shows.

There are at most eleven structured calls: six role analyses, one reviewer, six revisions
(six in practice only when every dimension is revised; a public run without verified
positions has five). Tool acquisition adds at most five calls: two review-requested
supplements plus three ledger-driven retries, not model calls. Target after
the latency work below is roughly a single-mode run plus one review round; it has not been
re-measured against a live provider yet, so treat it as a budget, not a result.
Progress merging does not regress after late callbacks. Logs record role/review duration,
input characters, per-role coverage status with met/missing counts, supplement counts and
acquisition ok/empty/failed/not_attempted counts.
The current implementation runs within the chat request, with explicit progress,
cancellation and checkpoint continuation. It does not introduce a detached Taskiq research
worker or independent conversations for each role. Providers must support the LLM service's
structured-output path. Automated tests use model/tool substitutes; actual research
quality, provider compatibility, latency and costs must be measured with live evals.

## Examples and reproducible verification

The design applies [LangGraph parallelization and evaluator-optimizer examples](https://docs.langchain.com/oss/python/langgraph/workflows-agents),
[subagent context isolation](https://docs.langchain.com/oss/python/langchain/multi-agent/subagents)
and [checkpoint persistence](https://docs.langchain.com/oss/python/langgraph/persistence).
Known research dimensions use deterministic assignment, parallel independent roles
and feedback-based revisions with the existing checkpoint nodes.

Tests cover clean reviews, targeted revisions, parallel supplements, failed position
reads, cross-object citations, dropped forged references, derived coverage states,
invalid feedback, timeouts, cancellation/resume, synthesis failure and late progress.
Live-eval metrics under `backend/evals/metrics/prompts/` score the published report on
`multi_role_dimension_coverage`, `multi_role_incremental_value` (does it say anything a
single pass over the same evidence would not) and `multi_role_verifiability`.
Run `python -m scripts.benchmark_multi_role --delay-ms 100 --runs 5` for the controlled
communication-stage benchmark. Re-measured against the derived-coverage contract, the
five-run median was 320.33ms for the fixed reference (five dimensions, always two rounds,
11 structured calls) and 229.16ms for the optimized graph (6 calls: five dimensions plus
one clean review, no revisions). It uses a model substitute and excludes evidence
collection and final synthesis; it is not a real-provider or end-to-end speed claim.
Results are saved to `.runtime/multi-role-benchmark.json`.
`python -m scripts.compare_research_modes --yes-live --fund-code <code>` is the real-provider
counterpart: it drives a running API with the same question in both tiers and reports
client-visible TTFT, total time, section/citation counts, the code-generated footer and the
`research_progress`/`research_activity` frame counts. It writes to
`.runtime/research-mode-comparison.json` and must never run in CI.
First live baseline (2026-10-18, `glm-5.3-flash`, fund 000001, same question, same session):
single 38.41s to first character / 75.58s total / 25 citations with 0 unverifiable;
multi-role 97.5s / 129.98s / 24 citations with 0 unverifiable, 27 `research_progress` frames
and 0 `research_activity` frames. Both tiers now carry the code-generated source check,
while only multi-role carries the dimension sections and the scope footer. The activity line
is dead by construction today: `ProgressChatOpenAI` deliberately keeps only the *length* of
`reasoning_content`, and a `function_calling` answer streams empty `token` values, so the
observer at `services/llm/timeouts.py` never receives a fragment. Fixing it needs a product
decision (show a benign "thought N characters" line, or stop shipping the field), not a patch
that leaks hidden reasoning to the client.
## Offline multi-role fixture evaluation

`evals/fixtures/multi_role/cases.json` holds fixed evidence packs and expectations, and
`evals/multi_role_eval.py` drives the real multi-role subgraph with deterministic model,
tool and reviewer substitutes. It never calls the network or writes to the database:

```bash
python -m scripts.eval_multi_role --output .runtime/multi-role-eval.json
```

The report records per-case coverage, unknown citations, revision roles, duplicate claims,
call counts and estimated tokens, plus aggregate unknown-citation rate, mean calls and
maximum graph time. `tests/test_multi_role_eval.py` runs the same fixtures as a pytest gate.

Live evaluations must compare latency, complete/partial rates and human-checked
semantic support with the same model and research targets before tightening budgets.
