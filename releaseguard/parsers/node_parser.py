"""Parse Node.js test runner stdout/stderr into structured results."""

from __future__ import annotations

import re

from releaseguard.models.core import TestFailure, TestRunResult


# ---------------------------------------------------------------------------
# ANSI escape-code stripper
# Needed because Node.js built-in test runner emits coloured/decorated output
# even when stdout is not a TTY in some environments.
# ---------------------------------------------------------------------------

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


# ---------------------------------------------------------------------------
# Node built-in test runner (node:test) summary block
#
# Node v18+ emits a diagnostic summary to stderr that looks like:
#
#   ℹ tests 2          (Unicode INFO SIGN U+2139, or plain ASCII when piped)
#   ℹ pass 2
#   ℹ fail 0
#   ℹ skipped 0
#   ℹ cancelled 0
#   ℹ duration_ms 42.123
#
# The "ℹ" prefix may be followed by a space, or it may be absent entirely
# (when output is piped / not a TTY).  ANSI codes may also wrap the prefix.
# We therefore match the keyword anywhere on each line (not anchored at ^).
# ---------------------------------------------------------------------------

# Each pattern: optional leading junk (ℹ, ANSI, spaces) then the keyword
_NODE_TESTS_RE = re.compile(r"\btests\s+(\d+)", re.MULTILINE)
_NODE_PASS_RE  = re.compile(r"\bpass\s+(\d+)", re.MULTILINE)
_NODE_FAIL_RE  = re.compile(r"\bfail\s+(\d+)", re.MULTILINE)
_NODE_SKIP_RE  = re.compile(r"\bskipped?\s+(\d+)", re.MULTILINE | re.IGNORECASE)

# TAP "not ok" line emitted by the Node runner per failing test
_NOT_OK_RE = re.compile(r"not ok\s+\d+\s*-?\s*(.+)")

# ---------------------------------------------------------------------------
# Mocha / Jest-style summary lines
#
# Mocha:
#   "  5 passing (42ms)"
#   "  1 failing"
#   "  2 pending"
#
# Jest:
#   "Tests: 2 failed, 5 passed, 7 total"
# ---------------------------------------------------------------------------

_MOCHA_PASS_RE = re.compile(r"(\d+)\s+passing", re.IGNORECASE)
_MOCHA_FAIL_RE = re.compile(r"(\d+)\s+failing", re.IGNORECASE)
_MOCHA_PEND_RE = re.compile(r"(\d+)\s+pending", re.IGNORECASE)

_JEST_TESTS_RE = re.compile(
    r"Tests:\s+"
    r"(?:(\d+)\s+failed,\s*)?"
    r"(?:(\d+)\s+skipped,\s*)?"
    r"(?:(\d+)\s+passed,\s*)?"
    r"(\d+)\s+total",
    re.IGNORECASE,
)

# Jest individual failure bullets: "  ● SuiteName > test name"
_JEST_FAIL_NAME_RE = re.compile(r"^\s+●\s+(.+)$", re.MULTILINE)

# Mocha numbered failure items: "  1) suite name test name"
_MOCHA_FAIL_NAME_RE = re.compile(r"^\s+\d+\)\s+(.+)$", re.MULTILINE)


def parse_node(result: TestRunResult) -> TestRunResult:
    """Populate *result* with parsed counts and failures from Node.js test output.

    Detection order:
    1. Node built-in test runner (``node:test``) — ``ℹ tests N`` style summary
    2. Jest ``Tests: N passed, N total`` summary line
    3. Mocha ``N passing`` / ``N failing`` lines

    Mutates *result* in-place and returns it.
    """
    # Strip ANSI codes so regex anchors work reliably
    raw = result.stdout + "\n" + result.stderr
    output = _strip_ansi(raw)

    # --- 1. Node built-in runner ---
    m_tests = _NODE_TESTS_RE.search(output)
    m_pass  = _NODE_PASS_RE.search(output)
    m_fail  = _NODE_FAIL_RE.search(output)
    m_skip  = _NODE_SKIP_RE.search(output)

    if m_tests or m_pass or m_fail:
        result.passed  = int(m_pass.group(1))  if m_pass  else 0
        result.failed  = int(m_fail.group(1))  if m_fail  else 0
        result.skipped = int(m_skip.group(1))  if m_skip  else 0
        result.total   = int(m_tests.group(1)) if m_tests else (
            (result.passed or 0) + (result.failed or 0) + (result.skipped or 0)
        )
        _extract_node_failures(result, output)
        return result

    # --- 2. Jest ---
    m_jest = _JEST_TESTS_RE.search(output)
    if m_jest:
        result.failed  = int(m_jest.group(1)) if m_jest.group(1) else 0
        result.skipped = int(m_jest.group(2)) if m_jest.group(2) else 0
        result.passed  = int(m_jest.group(3)) if m_jest.group(3) else 0
        result.total   = int(m_jest.group(4))
        _extract_jest_failures(result, output)
        return result

    # --- 3. Mocha ---
    m_mpass = _MOCHA_PASS_RE.search(output)
    m_mfail = _MOCHA_FAIL_RE.search(output)
    m_mpend = _MOCHA_PEND_RE.search(output)
    if m_mpass or m_mfail:
        result.passed  = int(m_mpass.group(1)) if m_mpass else 0
        result.failed  = int(m_mfail.group(1)) if m_mfail else 0
        result.skipped = int(m_mpend.group(1)) if m_mpend else 0
        result.total   = (result.passed or 0) + (result.failed or 0) + (result.skipped or 0)
        _extract_mocha_failures(result, output)
        return result

    return result


# ---------------------------------------------------------------------------
# Failure name extraction helpers
# ---------------------------------------------------------------------------

def _extract_node_failures(result: TestRunResult, output: str) -> None:
    """Extract failure names from Node built-in runner TAP ``not ok`` lines."""
    for m in _NOT_OK_RE.finditer(output):
        name = m.group(1).strip()
        if name:
            result.failures.append(TestFailure(name=name))


def _extract_jest_failures(result: TestRunResult, output: str) -> None:
    for m in _JEST_FAIL_NAME_RE.finditer(output):
        name = m.group(1).strip()
        if name:
            result.failures.append(TestFailure(name=name))


def _extract_mocha_failures(result: TestRunResult, output: str) -> None:
    for m in _MOCHA_FAIL_NAME_RE.finditer(output):
        name = m.group(1).strip()
        if name:
            result.failures.append(TestFailure(name=name))
