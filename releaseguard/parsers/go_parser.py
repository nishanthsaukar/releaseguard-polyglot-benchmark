"""Parse Go test runner stdout/stderr into structured results."""

from __future__ import annotations

import re

from releaseguard.models.core import TestFailure, TestRunResult


# ---------------------------------------------------------------------------
# ``go test`` output patterns
#
# Verbose (-v) individual test result:
#   "--- PASS: TestFoo (0.00s)"
#   "--- FAIL: TestFoo (0.01s)"
#   "--- SKIP: TestFoo (0.00s)"
#
# Package-level result:
#   "ok      github.com/user/repo  0.123s"
#   "FAIL    github.com/user/repo  0.123s"
#   "FAIL    github.com/user/repo [build failed]"
#
# Summary line (go test -v does NOT print a combined total line;
# individual counts must be aggregated from --- PASS/FAIL lines).
# ---------------------------------------------------------------------------

_TEST_PASS_RE = re.compile(r"^--- PASS:\s+(\S+)", re.MULTILINE)
_TEST_FAIL_RE = re.compile(r"^--- FAIL:\s+(\S+)", re.MULTILINE)
_TEST_SKIP_RE = re.compile(r"^--- SKIP:\s+(\S+)", re.MULTILINE)

# Package-level FAIL (not an individual test)
_PKG_FAIL_RE = re.compile(r"^FAIL\b", re.MULTILINE)
# Package-level ok (all passed)
_PKG_OK_RE = re.compile(r"^ok\s+\S+\s+[\d.]+s", re.MULTILINE)

# Build / compilation failures — "FAIL github.com/... [build failed]"
_BUILD_FAIL_RE = re.compile(r"\[build failed\]", re.IGNORECASE)


def parse_go(result: TestRunResult) -> TestRunResult:
    """Populate *result* with parsed counts and failures from ``go test`` output.

    Individual test counts are derived from ``--- PASS/FAIL/SKIP`` lines which
    are only present when running with ``-v``.  Without ``-v``, only the
    package-level PASS/FAIL is available; in that case only ``exit_code`` is
    reliable and counts are left as ``None``.

    Mutates *result* in-place and returns it.
    """
    output = result.stdout + "\n" + result.stderr

    # Build failures are a special case — no tests ran at all.
    if _BUILD_FAIL_RE.search(output):
        result.execution_error = "go build failed — no tests were executed"
        return result

    pass_names = _TEST_PASS_RE.findall(output)
    fail_names = _TEST_FAIL_RE.findall(output)
    skip_names = _TEST_SKIP_RE.findall(output)

    if pass_names or fail_names or skip_names:
        # Verbose output available — we can derive individual counts.
        result.passed = len(pass_names)
        result.failed = len(fail_names)
        result.skipped = len(skip_names)
        result.total = result.passed + result.failed + result.skipped
        for name in fail_names:
            result.failures.append(TestFailure(name=name))
    else:
        # Non-verbose: only package-level PASS/FAIL is known.
        # Populate failed=0/exit_code-derived rather than fabricating counts.
        if result.exit_code == 0:
            # All packages passed but we don't know individual counts.
            pass  # leave counts as None — no fabrication
        elif _PKG_FAIL_RE.search(output):
            # At least one package failed; individual counts unknown.
            result.execution_error = (
                "go test reported package-level FAIL; "
                "run with -v for individual test counts"
            )

    return result
