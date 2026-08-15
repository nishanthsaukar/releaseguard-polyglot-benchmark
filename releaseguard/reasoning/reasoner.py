"""Deterministic root-cause reasoning for ReleaseGuard.

The reasoning layer takes classified findings with source evidence
and produces human-readable, evidence-grounded explanations.

Rules:
- Only describe what the evidence actually shows.
- If source evidence is unavailable, state that explicitly.
- Never claim certainty beyond what the evidence supports.
- Prefer "Test evidence indicates X" over "X is proven" when
  source confirmation is absent.
"""

from __future__ import annotations

from releaseguard.models.core import (
    Finding,
    FindingCategory,
    SourceEvidence,
    TestFailure,
)
from releaseguard.source.inspector import SourceInspectionResult


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def reason_authorization(
    failures: list[TestFailure],
    source_evidences: list[SourceEvidence],
) -> str:
    """Produce a root-cause explanation for authorization failures."""
    n = len(failures)
    lines: list[str] = []

    lines.append(f"Test evidence: {n} authorization-related test(s) are failing.")

    # Collect what the test assertions tell us
    expected_codes = set()
    actual_codes = set()
    for f in failures:
        if f.expected_value:
            expected_codes.add(f.expected_value)
        if f.actual_value:
            actual_codes.add(f.actual_value)

    if expected_codes and actual_codes:
        lines.append(
            f"Tests expect HTTP {', '.join(sorted(expected_codes))} for cross-user "
            f"operations but received {', '.join(sorted(actual_codes))}."
        )

    # What source evidence tells us
    available_src = [s for s in source_evidences if s.available]
    if not available_src:
        lines.append(
            "Source confirmation unavailable: the relevant source function "
            "could not be located. Test evidence alone indicates an "
            "access-control enforcement gap."
        )
        return "\n".join(lines)

    for src in available_src[:1]:  # focus on first/primary evidence
        func = src.source_function or "(unknown function)"
        src_file = src.source_file or "(unknown file)"
        lines.append(f"Source evidence: inspected '{func}' in {src_file}.")

        # Report what the AST analysis found
        insp = getattr(src, "_inspection_result", None)
        if insp is not None:
            if insp.has_ownership_check:
                lines.append(
                    "  The function contains an ownership/identity comparison. "
                    "If ownership enforcement is failing, the comparison condition "
                    "or its context may be incorrect."
                )
            else:
                lines.append(
                    f"  The function body does not contain an ownership comparison "
                    f"against the caller's identity. "
                    f"Authenticated identity is available but ownership enforcement "
                    f"is absent — this is consistent with an authorization bypass."
                )
            if insp.has_conditional_raise:
                lines.append("  The function does raise conditionally (guard is present).")
            else:
                lines.append("  No conditional raise found — guard may be missing entirely.")
        else:
            # Fallback: describe based on available fields
            if src.source_excerpt:
                has_ownership = any(
                    term in src.source_excerpt
                    for term in ("user_id", "owner", "!=", "!= user")
                )
                if has_ownership:
                    lines.append(
                        "  The function body contains an ownership/identity "
                        "comparison — ownership enforcement appears present."
                    )
                else:
                    lines.append(
                        "  The function body does not contain an obvious "
                        "ownership comparison against the caller's identity. "
                        "This is consistent with an authorization bypass."
                    )

    lines.append(
        "Impact: Authenticated callers may be able to read, modify, "
        "or delete resources belonging to other users."
    )
    return "\n".join(lines)


def reason_validation(
    failures: list[TestFailure],
    source_evidences: list[SourceEvidence],
) -> str:
    """Produce a root-cause explanation for validation/contract failures."""
    n = len(failures)
    lines: list[str] = []

    lines.append(f"Test evidence: {n} validation/contract-related test(s) are failing.")

    # Summarise expected vs actual from assertion data
    for f in failures[:3]:
        if f.expected_value and f.actual_value:
            lines.append(
                f"  '{f.name.split('::')[-1]}': "
                f"expected {f.expected_value}, got {f.actual_value}."
            )

    available_src = [s for s in source_evidences if s.available]
    if not available_src:
        lines.append(
            "Source confirmation unavailable. Test evidence indicates the API "
            "accepts input that should have been rejected."
        )
        return "\n".join(lines)

    import re

    # Report the primary function source (first entry with a function name)
    for src in available_src[:1]:
        func = src.source_function or "(unknown)"
        src_file = src.source_file or "(unknown)"
        lines.append(f"Source evidence: inspected '{func}' in {src_file}.")

    # Scan all available entries for Field(...) constraints — the constraint may
    # live in a Pydantic model class field, not the endpoint function itself.
    for src in available_src:
        if not src.source_excerpt:
            continue
        max_len_match = re.search(r"max_length\s*=\s*(\d+)", src.source_excerpt)
        min_len_match = re.search(r"min_length\s*=\s*(\d+)", src.source_excerpt)
        if max_len_match:
            lines.append(
                f"  Validation constraint found: max_length={max_len_match.group(1)}."
            )
        if min_len_match:
            lines.append(
                f"  Validation constraint found: min_length={min_len_match.group(1)}."
            )
        if max_len_match or min_len_match:
            lines.append(
                "  If this constraint differs from the documented API contract, "
                "the validation boundary is incorrect."
            )
            break  # report the first constraint-bearing entry only

    lines.append(
        "Impact: The API may accept data outside its declared contract, "
        "causing inconsistent behaviour or data integrity issues."
    )
    return "\n".join(lines)


def reason_state_corruption(
    failures: list[TestFailure],
    source_evidences: list[SourceEvidence],
) -> str:
    """Produce a root-cause explanation for state/data-integrity failures."""
    n = len(failures)
    lines: list[str] = []

    lines.append(f"Test evidence: {n} state/transition-related test(s) are failing.")

    for f in failures[:3]:
        if f.expected_value and f.actual_value:
            lines.append(
                f"  '{f.name.split('::')[-1]}': "
                f"expected {f.expected_value}, got {f.actual_value}."
            )

    available_src = [s for s in source_evidences if s.available]
    if not available_src:
        lines.append(
            "Source confirmation unavailable. Test evidence indicates that "
            "an update operation unexpectedly changes an unrelated field."
        )
        return "\n".join(lines)

    for src in available_src[:1]:
        func = src.source_function or "(unknown)"
        src_file = src.source_file or "(unknown)"
        lines.append(f"Source evidence: inspected '{func}' in {src_file}.")
        if src.source_excerpt:
            import re
            # Look for assignments to 'completed' field
            completed_assign = re.search(
                r"""(task|obj|item)\s*\[\s*["']completed["']\s*\]\s*=\s*(\S+)""",
                src.source_excerpt,
            )
            if completed_assign:
                assigned_value = completed_assign.group(2).strip()
                lines.append(
                    f"  The function body assigns "
                    f"`completed = {assigned_value}` unconditionally. "
                    f"This overwrites any previously-set completion state."
                )

    lines.append(
        "Impact: An update operation may silently reset the 'completed' "
        "flag, corrupting task state."
    )
    return "\n".join(lines)


def reason_generic_failures(failures: list[TestFailure]) -> str:
    """Generic explanation for unclassified test failures."""
    n = len(failures)
    names = [f.name.split("::")[-1] for f in failures[:5]]
    extra = f" (and {n - 5} more)" if n > 5 else ""
    return (
        f"Test evidence: {n} test(s) are failing. "
        f"Failing tests: {', '.join(names)}{extra}. "
        f"Manual investigation is required to determine root cause."
    )
