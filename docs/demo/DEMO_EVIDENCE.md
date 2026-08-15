# ReleaseGuard Demo Evidence

## Clean baseline

Baseline tag:

	ask-manager-clean-v1

Expected benchmark result:

- Python: 69 passed, 0 failed
- ReleaseGuard decision: REVIEW_REQUIRED
- REVIEW_REQUIRED is caused only by unavailable npm and Maven tooling.

## Defect benchmark

Benchmark defects:

- benchmark-defect-01 — authorization bypass
- benchmark-defect-02 — title validation contract violation
- benchmark-defect-03 — completed-state corruption

Expected ReleaseGuard result:

- Python: 58 passed, 11 failed
- Authorization failures: 9
- Validation failure: 1
- State-transition failure: 1
- Release decision: BLOCKED

## Key demo message

ReleaseGuard does not merely report that tests failed.

It connects:

test failure
? risk category
? source evidence
? reasoning
? release decision.

## Demo safety

The benchmark application and benchmark tests are frozen.

Do not modify:

- python-app/
- benchmark/
- benchmark/ground-truth.md

The ReleaseGuard implementation should be changed only through deliberate, reviewable commits.
