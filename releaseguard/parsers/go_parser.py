"""Parse Go test runner stdout/stderr into structured results."""

from __future__ import annotations

import json
import re

from releaseguard.models.core import TestFailure, TestRunResult


# ---------------------------------------------------------------------------
# go test output patterns
#
# Verbose (-v) individual test results:
#   --- PASS: TestFoo (0.00s)
#   --- FAIL: TestFoo (0.01s)
#   --- SKIP: TestFoo (0.00s)
#
# Go JSON output (-json):
#   {"Action":"pass","Test":"TestFoo", ...}
#   {"Action":"fail","Test":"TestFoo", ...}
#   {"Action":"skip","Test":"TestFoo", ...}
# ---------------------------------------------------------------------------

_TEST_PASS_RE = re.compile(r"^--- PASS:\s+(\S+)", re.MULTILINE)
_TEST_FAIL_RE = re.compile(r"^--- FAIL:\s+(\S+)", re.MULTILINE)
_TEST_SKIP_RE = re.compile(r"^--- SKIP:\s+(\S+)", re.MULTILINE)

# Package-level failure.
_PKG_FAIL_RE = re.compile(r"^FAIL\b", re.MULTILINE)

# Build / compilation failure.
_BUILD_FAIL_RE = re.compile(r"\[build failed\]", re.IGNORECASE)


def parse_go(result: TestRunResult) -> TestRunResult:
    """Populate result with parsed counts and failures from Go test output.

    Parsing order:
    1. Go machine-readable JSON output (`go test -json`)
    2. Verbose output (`go test -v`)
    3. Normal package-level output, where counts remain unknown
    """

    output = result.stdout + "\n" + result.stderr

    # Build failures mean tests did not execute successfully.
    if _BUILD_FAIL_RE.search(output):
        result.execution_error = "go build failed — no tests were executed"
        return result

    # ------------------------------------------------------------------
    # 1. Go JSON output
    # ------------------------------------------------------------------
    if _try_parse_json(result, output):
        return result

    # ------------------------------------------------------------------
    # 2. Verbose output fallback
    # ------------------------------------------------------------------
    pass_names = _TEST_PASS_RE.findall(output)
    fail_names = _TEST_FAIL_RE.findall(output)
    skip_names = _TEST_SKIP_RE.findall(output)

    if pass_names or fail_names or skip_names:
        result.passed = len(pass_names)
        result.failed = len(fail_names)
        result.skipped = len(skip_names)
        result.total = (
            result.passed
            + result.failed
            + result.skipped
        )

        for name in fail_names:
            result.failures.append(TestFailure(name=name))

        return result

    # ------------------------------------------------------------------
    # 3. Normal non-verbose output
    #
    # Do not fabricate counts from:
    #     ok package/path (cached)
    # ------------------------------------------------------------------
    if result.exit_code != 0 and _PKG_FAIL_RE.search(output):
        result.execution_error = (
            "go test reported package-level FAIL; "
            "individual test counts could not be determined"
        )

    return result


def _try_parse_json(
    result: TestRunResult,
    output: str,
) -> bool:
    """Parse Go events produced by `go test -json`.

    Only individual events containing a `Test` field are counted.
    Package-level events are ignored.

    Returns True when valid JSON test events were successfully parsed.
    Returns False when the output is not Go JSON output.
    """

    passed_names: set[str] = set()
    failed_names: set[str] = set()
    skipped_names: set[str] = set()

    failure_output: dict[str, list[str]] = {}

    found_test_event = False

    for line in output.splitlines():
        line = line.strip()

        if not line:
            continue

        # Go JSON output should consist of JSON objects.
        if not line.startswith("{"):
            return False

        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return False

        test_name = event.get("Test")
        action = event.get("Action")

        # Package-level events do not have a Test field.
        if not test_name:
            continue

        found_test_event = True

        if action == "pass":
            passed_names.add(test_name)

        elif action == "fail":
            failed_names.add(test_name)

        elif action == "skip":
            skipped_names.add(test_name)

        elif action == "output":
            failure_output.setdefault(test_name, []).append(
                event.get("Output", "")
            )

    if not found_test_event:
        return False

    # A test can have intermediate events, but its final result should
    # be one of pass/fail/skip.
    result.passed = len(passed_names)
    result.failed = len(failed_names)
    result.skipped = len(skipped_names)

    result.total = (
        result.passed
        + result.failed
        + result.skipped
    )

    # Add structured failures.
    for test_name in sorted(failed_names):
        error_text = "".join(
            failure_output.get(test_name, [])
        ).strip()

        result.failures.append(
            TestFailure(
                name=test_name,
                error_text=error_text or None,
            )
        )

    return True