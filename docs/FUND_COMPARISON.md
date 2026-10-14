# Fund comparison research

Use `start_research(intent="fund_comparison", fund_queries=[...])` for an explicit comparison of two or three funds. Names are resolved sequentially using the existing confirmation flow. All objects must be confirmed before evidence collection. Aliases resolving to one code require another object; different A/C codes stay separate. Requests to analyze several funds individually retain `fund_research`.

The shared research graph loads `fund-comparison` and collects snapshots, manager records, disclosed holdings and one `get_fund_comparison_data` result. Deep mode additionally uses existing announcement and market evidence. Public comparisons do not read the user's portfolio. Explicit personal scope uses the existing authenticated snapshot. Reports use the existing traced model call, Markdown tables and individual fund cards; no frontend changes or database migration are required.

## Quantitative contract

- The tool accepts only two or three six-digit codes. Duplicate codes are removed; fewer than two distinct codes are rejected. It does not accept identity, amounts or supplied NAV series.
- All histories are requested over the same preceding year, anchored to `business_today()`. Reads are sequential with a seven-second per-fund deadline, within the graph's 25-second tool deadline.
- Invalid points and conflicting dates are removed using the existing normalization. At most 1,000 points per fund are processed. Source truncation is disclosed.
- The common window uses the first and last dates in the intersection of **all** requested funds' valid dates. Failed funds remain in the result; the tool does not silently compare a successful subset. Fewer than two common dates yields `unavailable`.
- NAV change is calculated on the common endpoints. Risk metrics require clean, matching date coverage in that window, no gap over 14 calendar days and at least 0.45 observations per calendar day (a conservative density heuristic, not an exchange-calendar validation). Annualized volatility additionally requires 120 observations and uses the existing 252-day convention. Missing metrics remain null.
- `partial` identifies shortened, stale, truncated or otherwise incomplete evidence. Every row retains its observed bounds, sample counts and gaps. No interpolation or forward filling is performed.
- Metrics describe unadjusted unit NAV, not distribution-adjusted or fee-adjusted total returns. Dates alone do not establish comparable fund types, currencies or objectives. Currency and complete fee data are not supplied by these tools. Money-market yield, peer rankings, correlations and full holdings overlap are outside this contract.

The model explains the computed evidence and conditional suitability. It must not calculate rankings from mismatched snapshot metrics or claim that individual fund cards share the comparison window. Holdings retain their disclosure periods and limited coverage.

## Verification

Run `python -m pytest -q tests/test_fund_comparison.py tests/test_research_workflow.py tests/test_research_extensions.py tests/test_fund_analysis_skill.py`, plus the project's Ruff and Pyright checks. Tests use simulated histories and model responses, covering alignment, short/stale/conflicting data, source failure, timeout/cancellation, duplicate aliases, sequential confirmations, streaming and personal scope. Live provider and model quality require a separate integration/evaluation run.
