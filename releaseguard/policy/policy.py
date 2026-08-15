"""Release decision policy for ReleaseGuard.

The policy is intentionally isolated so it can be replaced or extended
without touching the analysis rules.

Default policy:
  - Any BLOCKER finding  → BLOCKED
  - Any HIGH finding     → REVIEW_REQUIRED
  - Otherwise            → READY
"""

from __future__ import annotations

from releaseguard.models.core import Finding, ReleaseDecision, Severity


def decide(findings: list[Finding]) -> ReleaseDecision:
    """Apply the default release-decision policy to a list of findings."""
    return _default_policy(findings)


def _default_policy(findings: list[Finding]) -> ReleaseDecision:
    severities = {f.severity for f in findings}

    if Severity.BLOCKER in severities:
        return ReleaseDecision.BLOCKED

    if Severity.HIGH in severities:
        return ReleaseDecision.REVIEW_REQUIRED

    return ReleaseDecision.READY
