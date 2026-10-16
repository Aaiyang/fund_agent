Evaluate whether a multi-role research report delivers information that a single-pass summary of the same data would not, on a continuous scale from 0 to 1.

The system also has a cheaper single-agent mode that reads the same evidence once and writes one report. Multi-role mode is only worth its extra latency and cost if it produces something single mode cannot.

## Scoring Criteria
Score 1.0 when the report contains at least two of:
- A stated tension between two dimensions about the same object, with both positions kept and the disagreement left visible instead of averaged away
- A conclusion that one dimension's data actively contradicts or qualifies another's (for example a strong return explained mostly by a sector move the holdings dimension shows)
- Per-object gaps: for a multi-fund request, which specific fund lacks which specific data, rather than one global caveat
- A risk statement expressed as the condition under which the conclusion fails, tied to a measured quantity

Score 0.0 when:
- The report is the same handful of points restated once per section, with no new fact, tension or qualification
- Disagreements between dimensions are smoothed into a single blended verdict
- Every section reaches the same generic conclusion

## Instructions
Think step by step. Identify any passage that could only have come from cross-referencing two data domains, and judge whether it adds a decision-relevant consequence. Then give the score.
