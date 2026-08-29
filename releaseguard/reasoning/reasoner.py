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

import re

from releaseguard.models.core import (
    FindingCategory,
    SourceEvidence,
    TestFailure,
)


# ---------------------------------------------------------------------------
# Authorization reasoning
# ---------------------------------------------------------------------------


def reason_authorization(
    failures: list[TestFailure],
    source_evidences: list[SourceEvidence],
) -> str:
    """Produce a root-cause explanation for authorization failures."""

    n = len(failures)
    lines: list[str] = []

    lines.append(
        f"Test evidence: {n} authorization-related test(s) are failing."
    )

    expected_codes: set[str] = set()
    actual_codes: set[str] = set()

    for failure in failures:
        if failure.expected_value:
            expected_codes.add(failure.expected_value)

        if failure.actual_value:
            actual_codes.add(failure.actual_value)

    if expected_codes and actual_codes:
        lines.append(
            f"Tests expect HTTP {', '.join(sorted(expected_codes))} "
            f"for cross-user operations but received "
            f"{', '.join(sorted(actual_codes))}."
        )

    available_src = [
        source
        for source in source_evidences
        if source.available
    ]

    if not available_src:
        lines.append(
            "Source confirmation unavailable: the relevant source "
            "function could not be located. Test evidence alone "
            "indicates a possible access-control enforcement gap."
        )
        return "\n".join(lines)

    src = available_src[0]

    func = src.source_function or "(unknown function)"
    src_file = src.source_file or "(unknown file)"

    lines.append(
        f"Source evidence: inspected '{func}' in {src_file}."
    )

    inspection = getattr(src, "_inspection_result", None)

    if inspection is not None:
        if inspection.has_ownership_check:
            lines.append(
                "The inspected function contains an ownership or "
                "identity comparison. If authorization is failing, "
                "the comparison condition or its execution context "
                "may be incorrect."
            )
        else:
            lines.append(
                "The inspected function does not contain an ownership "
                "comparison against the caller's identity. This is "
                "consistent with a possible authorization bypass."
            )

        if inspection.has_conditional_raise:
            lines.append(
                "A conditional guard is present in the function."
            )
        else:
            lines.append(
                "No conditional rejection guard was found."
            )

    elif src.source_excerpt:
        excerpt = src.source_excerpt

        ownership_terms = (
            "user_id",
            "owner",
            "owner_id",
            "current_user",
        )

        has_identity_reference = any(
            term in excerpt
            for term in ownership_terms
        )

        has_comparison = any(
            operator in excerpt
            for operator in ("!=", "==")
        )

        if has_identity_reference and has_comparison:
            lines.append(
                "The available source excerpt contains an identity "
                "or ownership comparison."
            )
        else:
            lines.append(
                "The available source excerpt does not contain an "
                "obvious ownership comparison against the caller's "
                "identity. This is consistent with a possible "
                "authorization bypass."
            )

    lines.append(
        "Impact: Authenticated callers may be able to access or modify "
        "resources belonging to other users if ownership enforcement "
        "is missing or ineffective."
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Validation / API contract reasoning
# ---------------------------------------------------------------------------


def reason_validation(
    failures: list[TestFailure],
    source_evidences: list[SourceEvidence],
) -> str:
    """Produce a root-cause explanation for validation/contract failures."""

    n = len(failures)
    lines: list[str] = []

    lines.append(
        f"Test evidence: {n} validation/contract-related test(s) are failing."
    )

    for failure in failures[:3]:
        if failure.expected_value and failure.actual_value:
            test_name = failure.name.split("::")[-1]

            lines.append(
                f"'{test_name}': expected "
                f"{failure.expected_value}, got "
                f"{failure.actual_value}."
            )

    available_src = [
        source
        for source in source_evidences
        if source.available
    ]

    if not available_src:
        lines.append(
            "Source confirmation unavailable. Test evidence indicates "
            "that the API may accept input that should have been rejected."
        )
        return "\n".join(lines)

    primary = available_src[0]

    func = primary.source_function or "(unknown)"
    src_file = primary.source_file or "(unknown)"

    lines.append(
        f"Source evidence: inspected '{func}' in {src_file}."
    )

    constraint_found = False

    for source in available_src:
        if not source.source_excerpt:
            continue

        excerpt = source.source_excerpt

        max_length_match = re.search(
            r"max_length\s*=\s*(\d+)",
            excerpt,
        )

        min_length_match = re.search(
            r"min_length\s*=\s*(\d+)",
            excerpt,
        )

        if max_length_match:
            lines.append(
                "Validation constraint found: "
                f"max_length={max_length_match.group(1)}."
            )
            constraint_found = True

        if min_length_match:
            lines.append(
                "Validation constraint found: "
                f"min_length={min_length_match.group(1)}."
            )
            constraint_found = True

        if constraint_found:
            lines.append(
                "If this constraint differs from the expected API "
                "contract, the validation boundary is incorrect."
            )
            break

    if not constraint_found:
        lines.append(
            "No explicit length constraint was identified in the "
            "available source evidence."
        )

    lines.append(
        "Impact: The API may accept data outside its declared contract, "
        "causing inconsistent behaviour or data integrity issues."
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# State corruption reasoning
# ---------------------------------------------------------------------------


def reason_state_corruption(
    failures: list[TestFailure],
    source_evidences: list[SourceEvidence],
) -> str:
    """Produce a root-cause explanation for state/data-integrity failures."""

    n = len(failures)
    lines: list[str] = []

    lines.append(
        f"Test evidence: {n} state/transition-related test(s) are failing."
    )

    for failure in failures[:3]:
        if failure.expected_value and failure.actual_value:
            test_name = failure.name.split("::")[-1]

            lines.append(
                f"'{test_name}': expected "
                f"{failure.expected_value}, got "
                f"{failure.actual_value}."
            )

    available_src = [
        source
        for source in source_evidences
        if source.available
    ]

    if not available_src:
        lines.append(
            "Source confirmation unavailable. Test evidence indicates "
            "that an update operation may unexpectedly change an "
            "unrelated field."
        )
        return "\n".join(lines)

    src = available_src[0]

    func = src.source_function or "(unknown)"
    src_file = src.source_file or "(unknown)"

    lines.append(
        f"Source evidence: inspected '{func}' in {src_file}."
    )

    assignment_found = False

    for source in available_src:
        if not source.source_excerpt:
            continue

        excerpt = source.source_excerpt

        # Matches:
        # task["completed"] = False
        # task['completed'] = True
        # obj["completed"] = value
        completed_assign = re.search(
            r"""
            \b
            (?:task|obj|item|data)
            \s*
            \[
            \s*
            ["']completed["']
            \s*
            \]
            \s*=\s*
            ([^\n]+)
            """,
            excerpt,
            re.VERBOSE,
        )

        if completed_assign:
            assigned_value = completed_assign.group(1).strip()

            lines.append(
                "Source evidence indicates that the function assigns "
                f"`completed = {assigned_value}`."
            )

            lines.append(
                "If this assignment occurs independently of the "
                "requested update data, it can overwrite previously "
                "stored completion state."
            )

            assignment_found = True
            break

    if not assignment_found:
        lines.append(
            "No direct assignment to the `completed` field was found "
            "in the available source evidence."
        )

    lines.append(
        "Impact: An update operation may silently alter completion "
        "state, causing task state corruption."
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Generic reasoning
# ---------------------------------------------------------------------------


def reason_generic_failures(
    failures: list[TestFailure],
) -> str:
    """Generic explanation for unclassified test failures."""

    n = len(failures)

    names = [
        failure.name.split("::")[-1]
        for failure in failures[:5]
    ]

    extra = f" (and {n - 5} more)" if n > 5 else ""

    return (
        f"Test evidence: {n} test(s) are failing. "
        f"Failing tests: {', '.join(names)}{extra}. "
        "Manual investigation is required to determine the underlying cause."
    )


# ---------------------------------------------------------------------------
# Finding dispatcher
# ---------------------------------------------------------------------------


def generate_reasoning(
    category: FindingCategory,
    failures: list[TestFailure],
    source_evidences: list[SourceEvidence],
) -> str:
    """Generate deterministic reasoning for a classified finding."""

    if category == FindingCategory.AUTHORIZATION:
        return reason_authorization(
            failures,
            source_evidences,
        )

    if category in (
        FindingCategory.VALIDATION,
        FindingCategory.API_CONTRACT,
    ):
        return reason_validation(
            failures,
            source_evidences,
        )

    if category == FindingCategory.STATE_TRANSITION:
        return reason_state_corruption(
            failures,
            source_evidences,
        )

    return reason_generic_failures(failures)