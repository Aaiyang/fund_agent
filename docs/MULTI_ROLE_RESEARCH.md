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

## Communication protocol

The existing intent-specific research graph embeds `multi_role_agents` after its
deterministic evidence and scenario nodes:

1. Code assigns up to four object-scoped tasks per role and persists a bounded evidence
   packet and stage start time. Fundamentals and risk analyze role-relevant sources in
   parallel. Portfolio runs only with successful position evidence. Public research
   skips private ledger reads; fundamentals receives no private positions or unrelated
   market prose.
2. A join barrier waits for all roles, including explicit skipped/failed envelopes.
3. The reviewer receives original evidence and all first-round reports. Its feedback
   points to a role and finding index. Unknown claim targets, evidence IDs and funds
   are rejected and disclosed as gaps.
4. At most two independent supplement requests execute in parallel, from a fixed read-only whitelist:
   announcements (10), managers (20), or market events (10 within 168 hours). Arguments
   are constructed by the server and identical calls are deduplicated.
5. Only roles targeted by valid issues, relevant new evidence or omitted coverage records
   revise once. Review failure does not trigger a full rewrite. Unnecessary revisions
   reuse reviewed first-round work. Failed revisions preserve useful first-round findings
   while explicitly disclosing unresolved feedback.
6. One synthesis receives a machine-checked completion matrix, produces the final answer and preserves meaningful disagreement,
   limitations and missing evidence. Agent consensus is not independent factual support.

The server assigns each envelope's task ID, sender and round. The reducer merges by
`(run_id, role, round)`, sorts deterministically, accepts identical replay, and rejects
conflicting writes or mixed runs. Evidence IDs hash the task ID and exact bounded
evidence content. Claims referencing unavailable IDs are dropped, not repaired by
guessing. Existence checks do not prove semantic support: the reviewer performs that
assessment, and model judgments still require quality evaluation.

## Completion contract

`research_contract.py` derives assignments from the original intent and every confirmed
fund, without an additional planner model. Product/risk tasks cover each fund; comparison
adds a shared-window task; personal scope adds ledger/fit tasks; allocation adds a code
scenario task. Role output includes `coverage` pointing to task IDs, finding indices
and sources used by those findings. Validation checks visible references, object codes,
required sources and actual findings, then remaps indices after rejected findings.
Missing coverage, unknown tasks or evidence for another share class cannot count as
completed. An unavailable code scenario cannot be completed using ledger references.

Revisions acknowledge their assigned feedback via `addressed_issue_indices`. This
checks presence and ownership, not semantic adequacy. The first reviewer and final
synthesizer still make model judgments; no extra post-revision review loop is added.
Any blocked task, failed review, required failed revision or disclosed evidence gap
makes the overall result partial. Scope stays at the existing maximum of three funds.
The server appends a compact scope/coverage note so the synthesizer cannot silently
omit confirmed objects or blocked tasks. Sources flagged partial or stale keep the
overall result partial and their limitations remain in the published note.

Follow-up memory retrieval uses the original research question. The portfolio role
receives confirmed constraints from the existing persona service and, separately,
up to 2000 characters of relevant historical statements. Truncated or unconfirmed
memory does not override the current request or confirmed profile. Product analysis
receives no private profile.

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
unfinished checkpoints without replaying completed graph nodes. Individual role or
review failures produce a partial report; they do not trigger an unbounded debate.

All role calls use the existing user-scoped LLM service, structured Pydantic outputs,
tenacity retry/fallback and inherited Langfuse callbacks. One-off structured calls do
not change shared tool bindings or the user's active-model index. Configure:

- `FUND_MULTI_ROLE_RESEARCH_CALL_TIMEOUT=90`: deadline for each analysis/review/revision.
- `FUND_MULTI_ROLE_RESEARCH_TOTAL_TIMEOUT=180`: total communication budget including
  supplements, persisted across resume. Initial evidence and final synthesis retain
  their existing separate deadlines. Expiry preserves available work with explicit gaps.
- `FUND_MULTI_ROLE_RESEARCH_MAX_TOKENS=1600`: output budget, bounded to 256–2400.

There are at most seven structured calls plus one synthesis (three analysis roles,
one reviewer, three revisions). A clean review without supplements reduces public
research from five structured calls to three, or from seven to four with portfolio.
Progress merging does not regress after late callbacks. Logs record role/review duration,
input characters, completed task counts and supplement counts. The current
implementation runs within the chat request, with explicit progress, cancellation and
checkpoint continuation. It does not introduce a detached Taskiq research worker or
independent conversations for each role. Providers must support the LLM service's
structured-output path. Automated tests use model/tool substitutes; actual research
quality, provider compatibility, latency and costs must be measured with live evals.

## Examples and reproducible verification

The design applies [LangGraph parallelization and evaluator-optimizer examples](https://docs.langchain.com/oss/python/langgraph/workflows-agents),
[subagent context isolation](https://docs.langchain.com/oss/python/langchain/multi-agent/subagents)
and [checkpoint persistence](https://docs.langchain.com/oss/python/langgraph/persistence).
Known research dimensions use deterministic assignment, parallel independent roles
and feedback-based revisions with the existing checkpoint nodes.

Tests cover clean reviews, targeted revisions, parallel supplements, failed position
reads, cross-fund citations, index remapping, omitted tasks, invalid feedback,
timeouts, cancellation/resume, synthesis failure and late progress.
Run `python -m scripts.benchmark_multi_role --delay-ms 100 --runs 5` for the controlled
communication-stage benchmark. The five-run median was 327.25ms for a fixed two-round
reference scheduler and 226.02ms for the optimized graph. It uses a model substitute
and excludes evidence collection and final synthesis; it is not a real-provider or
end-to-end speed claim. Results are saved to `.runtime/multi-role-benchmark.json`.
Live evaluations must compare latency, complete/partial rates and human-checked
semantic support with the same model and research targets before tightening budgets.
