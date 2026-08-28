"""Parse Java (Maven Surefire / Gradle) test output into structured results."""

from __future__ import annotations

import re

from releaseguard.models.core import TestFailure, TestRunResult


# ---------------------------------------------------------------------------
# Maven Surefire output
#
# Per-class summary line:
#   "Tests run: 10, Failures: 1, Errors: 0, Skipped: 2 - in com.example.MyTest"
#
# Overall BUILD result:
#   "BUILD SUCCESS"
#   "BUILD FAILURE"
#
# Surefire failure message:
#   "FAILED: com.example.MyTest#testMethod"
# ---------------------------------------------------------------------------

_SUREFIRE_LINE_RE = re.compile(
    r"Tests run:\s*(\d+),\s*Failures:\s*(\d+),\s*Errors:\s*(\d+),\s*Skipped:\s*(\d+)"
    r"(?:\s*,\s*Time elapsed:[^-\n]*)?"
    r"(?:\s*<<<\s*FAILURE!)?"
    r"(?:\s*-\s*in\s+(\S+))?",
    re.IGNORECASE,
)

# Surefire individual failure indicator (appears before the per-class line)
_SUREFIRE_FAIL_RE = re.compile(
    r"^\[ERROR\]\s+(\S+(?:\.\w+)*)\s+Time elapsed.*?<<<\s*(FAILURE|ERROR)",
    re.MULTILINE,
)

# Surefire "Failed tests:" section
_FAILED_TESTS_HEADER_RE = re.compile(r"Failed tests:", re.IGNORECASE)
_FAILED_TEST_ITEM_RE = re.compile(r"^\s+(\S+\.\S+\(.*?\))", re.MULTILINE)

# Gradle test result
#   "X tests completed, Y failed"
#   "X tests completed, Y failed, Z skipped"
_GRADLE_SUMMARY_RE = re.compile(
    r"(\d+)\s+tests?\s+completed"
    r"(?:,\s*(\d+)\s+failed)?"
    r"(?:,\s*(\d+)\s+skipped)?",
    re.IGNORECASE,
)

# Gradle individual failure (task output)
#   "FAILED  com.example.MyTest > testMethod"
_GRADLE_FAIL_NAME_RE = re.compile(r"FAILED\s+(\S+\s+>\s+\S+)", re.MULTILINE)


def parse_java(result: TestRunResult) -> TestRunResult:
    """Populate *result* with parsed counts and failures from Maven/Gradle output.

    Aggregates across all Surefire per-class lines when present, then falls
    back to Gradle summary format.

    Mutates *result* in-place and returns it.
    """
    output = result.stdout + "\n" + result.stderr

    # --- Maven Surefire: aggregate across all per-class lines ---
    surefire_matches = _SUREFIRE_LINE_RE.findall(output)
    if surefire_matches:
        total = passed = failed = skipped = 0
        for run, fail, err, skip, _cls in surefire_matches:
            r, f, e, s = int(run), int(fail), int(err), int(skip)
            total += r
            failed += f + e          # Surefire "Errors" also block release
            skipped += s
        passed = total - failed - skipped
        result.total = total
        result.passed = max(passed, 0)
        result.failed = failed
        result.skipped = skipped
        _extract_surefire_failures(result, output)
        return result

    # --- Gradle ---
    m = _GRADLE_SUMMARY_RE.search(output)
    if m:
        result.total = int(m.group(1))
        result.failed = int(m.group(2)) if m.group(2) else 0
        result.skipped = int(m.group(3)) if m.group(3) else 0
        result.passed = max(result.total - result.failed - (result.skipped or 0), 0)
        _extract_gradle_failures(result, output)
        return result

    return result


def _extract_surefire_failures(result: TestRunResult, output: str) -> None:
    """Extract individual failure names from Maven Surefire output."""
    # Method 1: "[ERROR] com.example.MyTest  Time elapsed ... <<< FAILURE!"
    for m in _SUREFIRE_FAIL_RE.finditer(output):
        name = m.group(1).strip()
        if name:
            result.failures.append(TestFailure(name=name))
        return  # found structured failures; stop

    # Method 2: "Failed tests:" section
    header = _FAILED_TESTS_HEADER_RE.search(output)
    if header:
        section = output[header.end():]
        for m in _FAILED_TEST_ITEM_RE.finditer(section):
            name = m.group(1).strip()
            # Stop when we hit a non-indented block (next section)
            if not section[m.start():m.start() + 1].isspace():
                break
            result.failures.append(TestFailure(name=name))


def _extract_gradle_failures(result: TestRunResult, output: str) -> None:
    """Extract individual failure names from Gradle test output."""
    for m in _GRADLE_FAIL_NAME_RE.finditer(output):
        name = m.group(1).strip()
        if name:
            result.failures.append(TestFailure(name=name))
