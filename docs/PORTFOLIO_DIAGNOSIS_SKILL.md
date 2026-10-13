# Portfolio diagnosis skill

Builtin portfolio-diagnosis v1.0.0 uses tools v14, prompt fund-agent-v20 and skills registry v6. Instructions live at backend/app/agent/skills/portfolio-diagnosis/SKILL.md; evidence limits and card protocols live at references/evidence.md.

load_skill(skill_name="portfolio-diagnosis") loads instructions; request section="evidence" only when needed. Resources are packaged, allowlisted and read at module import. Each skill has its own version; fund-analysis remains v1.4.0. Paths, URLs, scripts and identity inputs are rejected. Existing agent execution and tracing are reused; routing depends on model tool selection, without a new enforced subgraph.

Portfolio-wide diagnosis routes here, while named-fund potential/performance research uses fund-analysis and simple balance queries use existing tools. Read get_portfolio and get_positions(limit=50) for the same authenticated account scope. Describe missing amounts, actual NAV dates, truncation and mismatched reads. Summary fund_count counts position rows, not distinct fund codes; data_updated_at is a fetch timestamp. Failed queries do not establish empty holdings.

The report covers portfolio facts and data quality, concentration and duplicate-disclosure clues, returns/risk and goal compatibility, then at most three evidence-backed priorities and conditional plans for 1–3 months, 3–6 months and 6+ months. Default public deep research is at most three distinct codes, reused across accounts with separate private costs. Extra tools are conditional; do not run the entire single-fund workflow for every position.

Current tools do not calculate aggregate Top3 weights, HHI, portfolio return history/drawdown/volatility, correlations, complete look-through overlap, optimized weights or rebalance amounts. These remain explicit gaps rather than model-generated numbers. Existing single-row weights and computed public fund metrics can be cited with their scopes. Missing cash or other assets cannot support whole-household allocation conclusions. Recommendations do not authorize writes or trades.

Use existing fund-chart v2 references and fund-holdings v1 disclosure cards only when useful. Mobile renders existing components and fetches backend data; no new UI protocol is required. A single-fund chart is not a portfolio return curve.

Regression tests cover allowlisting, per-skill versions, no request-time file reads, real graph/tool execution under authenticated scope, empty holdings, query failures and list truncation beyond fifty rows. Model and service responses are mocked; routing and diagnosis quality still need live-model evaluation.
