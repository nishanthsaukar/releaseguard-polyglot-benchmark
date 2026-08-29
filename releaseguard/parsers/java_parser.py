"""Parse Java (Maven Surefire / Gradle) test output into structured results."""

from __future__ import annotations

import re

from releaseguard.models.core import TestFailure, TestRunResult


# ===========================================================================
# Maven Surefire patterns
# ===========================================================================

# Matches both per-class and final Surefire summaries.
#
# Examples:
#
# Tests run: 10, Failures: 1, Errors: 0, Skipped: 2
#
# Tests run: 10, Failures: 1, Errors: 0, Skipped: 2 - in com.example.MyTest
#
# Tests run: 10, Failures: 1, Errors: 0, Skipped: 2, Time elapsed: 0.123 s
# - in com.example.MyTest

_SUREFIRE_SUMMARY_RE = re.compile(
    r"Tests run:\s*(\d+),\s*"
    r"Failures:\s*(\d+),\s*"
    r"Errors:\s*(\d+),\s*"
    r"Skipped:\s*(\d+)",
    re.IGNORECASE,
)


# A per-class Surefire summary contains:
#
# - in com.example.SomeTest

_SUREFIRE_CLASS_MARKER_RE = re.compile(
    r"-\s*in\s+\S+",
    re.IGNORECASE,
)


# Maven's final results section.
#
# [INFO] Results:

_SUREFIRE_RESULTS_RE = re.compile(
    r"\[INFO\]\s+Results:",
    re.IGNORECASE,
)


# Individual Surefire failure.
#
# [ERROR] com.example.MyTest.testSomething Time elapsed: 0.01 s <<< FAILURE!

_SUREFIRE_FAILURE_RE = re.compile(
    r"^\[ERROR\]\s+(.+?)\s+"
    r"Time elapsed:.*?<<<\s*(?:FAILURE|ERROR)!?",
    re.MULTILINE | re.IGNORECASE,
)


# Maven "Failed tests:" section.

_FAILED_TESTS_HEADER_RE = re.compile(
    r"Failed tests:",
    re.IGNORECASE,
)


# ===========================================================================
# Gradle patterns
# ===========================================================================

# Examples:
#
# 10 tests completed
# 10 tests completed, 2 failed
# 10 tests completed, 2 failed, 1 skipped

_GRADLE_SUMMARY_RE = re.compile(
    r"(\d+)\s+tests?\s+completed"
    r"(?:,\s*(\d+)\s+failed)?"
    r"(?:,\s*(\d+)\s+skipped)?",
    re.IGNORECASE,
)


# Example:
#
# FAILED com.example.MyTest > testSomething

_GRADLE_FAILURE_RE = re.compile(
    r"FAILED\s+(\S+\s+>\s+\S+)",
    re.MULTILINE,
)


# ===========================================================================
# Main parser
# ===========================================================================

def parse_java(result: TestRunResult) -> TestRunResult:
    """Populate result with parsed Maven Surefire or Gradle test results."""

    output = "\n".join(
        part
        for part in (result.stdout, result.stderr)
        if part
    )

    if not output.strip():
        return result

    if _parse_surefire(result, output):
        return result

    if _parse_gradle(result, output):
        return result

    return result


# ===========================================================================
# Maven Surefire parsing
# ===========================================================================

def _parse_surefire(
    result: TestRunResult,
    output: str,
) -> bool:
    """Parse Maven Surefire output.

    Rules:

    1. If Maven has a final '[INFO] Results:' section, use its final
       aggregate summary.

    2. If multiple per-class summaries exist without a final summary,
       aggregate them.

    3. If only one summary exists, use that summary.
    """

    matches = list(_SUREFIRE_SUMMARY_RE.finditer(output))

    if not matches:
        return False

    # -----------------------------------------------------------------------
    # Case 1: Maven final Results section exists.
    #
    # Example:
    #
    # Tests run: 10 ... - in SomeTest
    # [INFO] Results:
    # [INFO] Tests run: 10, Failures: 0, Errors: 0, Skipped: 0
    # -----------------------------------------------------------------------

    results_section = _SUREFIRE_RESULTS_RE.search(output)

    if results_section:
        summaries_after_results = [
            match
            for match in matches
            if match.start() > results_section.end()
        ]

        if summaries_after_results:
            _apply_surefire_match(
                result,
                summaries_after_results[-1],
            )

            _extract_surefire_failures(result, output)

            return True

    # -----------------------------------------------------------------------
    # Case 2: Only one summary.
    # -----------------------------------------------------------------------

    if len(matches) == 1:
        _apply_surefire_match(
            result,
            matches[0],
        )

        _extract_surefire_failures(result, output)

        return True

    # -----------------------------------------------------------------------
    # Case 3: Multiple summaries.
    #
    # Check which summaries are per-class summaries by looking for:
    #
    # - in com.example.SomeTest
    # -----------------------------------------------------------------------

    per_class_matches = []

    for match in matches:
        line_end = output.find("\n", match.start())

        if line_end == -1:
            line_end = len(output)

        line = output[match.start():line_end]

        if _SUREFIRE_CLASS_MARKER_RE.search(line):
            per_class_matches.append(match)

    # If every detected summary is a per-class summary, aggregate them.
    if per_class_matches and len(per_class_matches) == len(matches):
        _aggregate_surefire_matches(
            result,
            per_class_matches,
        )

        _extract_surefire_failures(result, output)

        return True

    # -----------------------------------------------------------------------
    # Case 4: Mixed or unknown format.
    #
    # Prefer the last summary because Maven normally prints the aggregate
    # summary at the end.
    # -----------------------------------------------------------------------

    _apply_surefire_match(
        result,
        matches[-1],
    )

    _extract_surefire_failures(result, output)

    return True


def _apply_surefire_match(
    result: TestRunResult,
    match: re.Match[str],
) -> None:
    """Apply one Maven Surefire summary."""

    total = int(match.group(1))
    failures = int(match.group(2))
    errors = int(match.group(3))
    skipped = int(match.group(4))

    # Both Failures and Errors represent unsuccessful tests.
    failed = failures + errors

    passed = total - failed - skipped

    result.total = total
    result.passed = max(passed, 0)
    result.failed = failed
    result.skipped = skipped


def _aggregate_surefire_matches(
    result: TestRunResult,
    matches: list[re.Match[str]],
) -> None:
    """Aggregate multiple Maven Surefire per-class summaries."""

    total = 0
    failed = 0
    skipped = 0

    for match in matches:
        tests = int(match.group(1))
        failures = int(match.group(2))
        errors = int(match.group(3))
        skipped_count = int(match.group(4))

        total += tests
        failed += failures + errors
        skipped += skipped_count

    passed = total - failed - skipped

    result.total = total
    result.passed = max(passed, 0)
    result.failed = failed
    result.skipped = skipped


# ===========================================================================
# Maven failure extraction
# ===========================================================================

def _extract_surefire_failures(
    result: TestRunResult,
    output: str,
) -> None:
    """Extract individual Maven Surefire failure names."""

    existing_names = {
        failure.name
        for failure in result.failures
    }

    # -----------------------------------------------------------------------
    # Method 1: Structured [ERROR] failure lines.
    # -----------------------------------------------------------------------

    found_structured_failures = False

    for match in _SUREFIRE_FAILURE_RE.finditer(output):
        name = match.group(1).strip()

        if name and name not in existing_names:
            result.failures.append(
                TestFailure(name=name)
            )

            existing_names.add(name)
            found_structured_failures = True

    if found_structured_failures:
        return

    # -----------------------------------------------------------------------
    # Method 2: "Failed tests:" section.
    # -----------------------------------------------------------------------

    header = _FAILED_TESTS_HEADER_RE.search(output)

    if not header:
        return

    section = output[header.end():]

    for line in section.splitlines():
        stripped = line.strip()

        if not stripped:
            continue

        # Stop when Maven starts another major section.
        if stripped.startswith("[INFO]"):
            break

        if stripped.startswith("[ERROR]"):
            break

        if stripped.lower().startswith("tests run:"):
            break

        if stripped.lower().startswith("results:"):
            break

        # Failure names in this section are normally indented.
        if line[:1].isspace():
            name = stripped

            if name and name not in existing_names:
                result.failures.append(
                    TestFailure(name=name)
                )

                existing_names.add(name)


# ===========================================================================
# Gradle parsing
# ===========================================================================

def _parse_gradle(
    result: TestRunResult,
    output: str,
) -> bool:
    """Parse Gradle test summary output."""

    match = _GRADLE_SUMMARY_RE.search(output)

    if not match:
        return False

    total = int(match.group(1))
    failed = int(match.group(2) or 0)
    skipped = int(match.group(3) or 0)

    passed = total - failed - skipped

    result.total = total
    result.passed = max(passed, 0)
    result.failed = failed
    result.skipped = skipped

    _extract_gradle_failures(result, output)

    return True


# ===========================================================================
# Gradle failure extraction
# ===========================================================================

def _extract_gradle_failures(
    result: TestRunResult,
    output: str,
) -> None:
    """Extract individual Gradle failure names."""

    existing_names = {
        failure.name
        for failure in result.failures
    }

    for match in _GRADLE_FAILURE_RE.finditer(output):
        name = match.group(1).strip()

        if name and name not in existing_names:
            result.failures.append(
                TestFailure(name=name)
            )

            existing_names.add(name)