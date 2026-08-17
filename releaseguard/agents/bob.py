from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BobInvestigation:
    """Structured investigation produced by Bob."""

    defect_id: str
    severity: str
    summary: str

    root_cause: str = ""
    reasoning: str = ""

    affected_files: list[str] = field(default_factory=list)
    affected_tests: list[str] = field(default_factory=list)

    confidence: float = 0.0

    proposed_fix: str = ""
    verification_plan: str = ""

    evidence: list[str] = field(default_factory=list)


def _get_value(
    obj: Any,
    name: str,
    default: Any = None,
) -> Any:
    """Safely read a field from either an object or dictionary."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _normalise_confidence(value: Any) -> float:
    """Convert confidence into a value between 0 and 1."""
    if value is None:
        return 0.0

    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0

    if confidence > 1:
        confidence /= 100

    return min(max(confidence, 0.0), 1.0)


def _extract_files(finding: Any) -> list[str]:
    """Extract affected files from a ReleaseGuard finding."""
    files = _get_value(finding, "affected_files", []) or []
    return [str(path) for path in files]


def _extract_tests(finding: Any) -> list[str]:
    """Extract affected tests from a ReleaseGuard finding."""
    tests = _get_value(finding, "affected_tests", []) or []
    return [str(test) for test in tests]


def _extract_evidence(finding: Any) -> list[str]:
    """Extract source evidence from a ReleaseGuard finding."""
    evidence: list[str] = []
    source_evidence = _get_value(finding, "source_evidence", []) or []

    for item in source_evidence:
        file_path = _get_value(item, "source_file")
        line = _get_value(item, "source_line")
        excerpt = _get_value(item, "source_excerpt")

        location = str(file_path or "Unknown")
        if line:
            location += f":{line}"

        if excerpt:
            evidence.append(f"{location}\n{excerpt}")
        else:
            evidence.append(location)

    return evidence


def _propose_fix(finding: Any) -> str:
    """
    Produce a conservative fix suggestion.

    Bob does not modify source code.
    """
    summary = str(_get_value(finding, "summary", ""))
    reasoning = str(_get_value(finding, "reasoning", ""))

    summary_upper = summary.upper()
    reasoning_upper = reasoning.upper()

    if "AUTH" in summary_upper or "AUTHORIZATION" in reasoning_upper:
        return (
            "Add an ownership check at the task lookup "
            "boundary so authenticated users can only "
            "access their own resources. Return 404 for "
            "missing or unauthorized resources."
        )

    if "VALID" in summary_upper or "LENGTH" in summary_upper:
        return (
            "Align the input validation constraint with "
            "the tested API contract and retain a regression "
            "test for the boundary."
        )

    if (
        "STATE" in summary_upper
        or "RESET" in summary_upper
        or "COMPLETED" in summary_upper
    ):
        return (
            "Update only the fields represented by the "
            "request payload and preserve existing state "
            "for fields not included in the update."
        )

    return (
        "Apply the smallest source-level change supported "
        "by the test and source evidence, then rerun the "
        "affected tests."
    )


def _verification_plan(finding: Any) -> str:
    """Create a verification plan for the proposed fix."""
    tests = _extract_tests(finding)

    if tests:
        return (
            "Apply the proposed change, rerun the affected "
            "tests, and confirm that previously passing tests "
            "remain green."
        )

    return (
        "Apply the proposed change and rerun the complete "
        "test suite to verify that the release risk is "
        "resolved."
    )


def investigate(findings: list[Any]) -> list[BobInvestigation]:
    """
    Investigate existing ReleaseGuard findings.

    This is intentionally read-only.

    Bob receives evidence that ReleaseGuard has already
    collected and produces structured investigations.

    Bob never edits repository files.
    """
    investigations: list[BobInvestigation] = []

    for index, finding in enumerate(findings, start=1):
        severity = str(_get_value(finding, "severity", "UNKNOWN")).upper()
        summary = str(_get_value(finding, "summary", "Release risk finding"))
        reasoning = str(_get_value(finding, "reasoning", ""))

        affected_files = _extract_files(finding)
        affected_tests = _extract_tests(finding)
        evidence = _extract_evidence(finding)

        investigation = BobInvestigation(
            defect_id=f"BOB-{index:02d}",
            severity=severity,
            summary=summary,
            root_cause=reasoning,
            reasoning=reasoning,
            affected_files=affected_files,
            affected_tests=affected_tests,
            confidence=_normalise_confidence(
                _get_value(finding, "confidence", 0.0)
            ),
            proposed_fix=_propose_fix(finding),
            verification_plan=_verification_plan(finding),
            evidence=evidence,
        )

        investigations.append(investigation)

    return investigations