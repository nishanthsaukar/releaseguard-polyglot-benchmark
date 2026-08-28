"""Parse Rust / Cargo test runner stdout/stderr into structured results."""

from __future__ import annotations

import re

from releaseguard.models.core import TestFailure, TestRunResult


# ---------------------------------------------------------------------------
# Cargo test output patterns
#
# Summary line:
#   "test result: ok. 5 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out"
#   "test result: FAILED. 4 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out"
#
# Individual test results (verbose):
#   "test my_module::test_something ... ok"
#   "test my_module::test_other    ... FAILED"
#   "test my_module::test_skip     ... ignored"
#
# Failure block header:
#   "---- my_module::test_other stdout ----"
# ---------------------------------------------------------------------------

_SUMMARY_RE = re.compile(
    r"test result:\s+\w+\.\s+"
    r"(\d+)\s+passed;\s+"
    r"(\d+)\s+failed;\s+"
    r"(\d+)\s+ignored",
    re.IGNORECASE,
)

# Individual test outcome lines
_TEST_OK_RE = re.compile(r"^test\s+(\S+)\s+\.\.\.\s+ok", re.MULTILINE)
_TEST_FAIL_RE = re.compile(r"^test\s+(\S+)\s+\.\.\.\s+FAILED", re.MULTILINE)
_TEST_IGNORE_RE = re.compile(r"^test\s+(\S+)\s+\.\.\.\s+ignored", re.MULTILINE)

# Failure output block header: "---- test::name stdout ----"
_FAIL_BLOCK_RE = re.compile(r"^----\s+(.+?)\s+stdout\s+----\s*\n(.*?)(?=^----|^\ntest result)", re.MULTILINE | re.DOTALL)

# Compilation/linker errors from Cargo
_COMPILE_ERROR_RE = re.compile(r"^error(\[E\d+\])?:", re.MULTILINE)


def parse_rust(result: TestRunResult) -> TestRunResult:
    """Populate *result* with parsed counts and failures from ``cargo test`` output.

    Mutates *result* in-place and returns it.
    """
    output = result.stdout + "\n" + result.stderr

    # Compilation error — no tests ran
    if _COMPILE_ERROR_RE.search(output) and result.exit_code != 0:
        # Only flag as compilation error when there is no summary line either
        if not _SUMMARY_RE.search(output):
            result.execution_error = "cargo test reported a compilation error"
            return result

    # Failure text blocks keyed by test name (for error_text enrichment)
    fail_blocks: dict[str, str] = {}
    for m in _FAIL_BLOCK_RE.finditer(output):
        fail_blocks[m.group(1).strip()] = m.group(2).strip()

    # --- Prefer the summary line (most reliable) ---
    m = _SUMMARY_RE.search(output)
    if m:
        result.passed = int(m.group(1))
        result.failed = int(m.group(2))
        result.skipped = int(m.group(3))   # "ignored" = skipped in Cargo
        result.total = result.passed + result.failed + result.skipped

        # Extract individual failure names from verbose lines
        fail_names = _TEST_FAIL_RE.findall(output)
        for name in fail_names:
            error_text = fail_blocks.get(name, "")
            result.failures.append(TestFailure(name=name, error_text=error_text))

        return result

    # --- Fallback: count individual test result lines (verbose without summary) ---
    ok_names = _TEST_OK_RE.findall(output)
    fail_names = _TEST_FAIL_RE.findall(output)
    ignore_names = _TEST_IGNORE_RE.findall(output)

    if ok_names or fail_names or ignore_names:
        result.passed = len(ok_names)
        result.failed = len(fail_names)
        result.skipped = len(ignore_names)
        result.total = result.passed + result.failed + result.skipped
        for name in fail_names:
            error_text = fail_blocks.get(name, "")
            result.failures.append(TestFailure(name=name, error_text=error_text))

    return result
