"""Parse pytest stdout/stderr into structured results."""

from __future__ import annotations

import re
from typing import Optional

from releaseguard.models.core import TestRunResult, TestFailure


# ---------------------------------------------------------------------------
# Summary line patterns
#
# pytest emits a final summary line like:
#   "58 passed, 11 failed in 1.23s"
#   "11 failed, 58 passed in 1.23s"
#   "69 passed in 0.98s"
#   "5 failed in 0.12s"
#   "2 passed, 1 skipped in 0.45s"
# ---------------------------------------------------------------------------

_SUMMARY_RE = re.compile(
    r"=+\s+"
    r"(?P<summary>[\w ,]+?)"
    r"\s+in\s+[\d.]+s"
    r"\s*=+",
    re.IGNORECASE,
)

_COUNT_RE = re.compile(r"(\d+)\s+(passed|failed|skipped|error(?:s)?|warning(?:s)?)")

# FAILED lines in verbose mode: "FAILED tests/test_app.py::Class::test_name"
_FAILED_LINE_RE = re.compile(r"^FAILED\s+(.+)$", re.MULTILINE)

# Short test summary section emitted by pytest at the end
_SHORT_SUMMARY_RE = re.compile(r"=+\s+short test summary info\s+=+", re.IGNORECASE)

# Traceback frame lines:  "  File "path/to/file.py", line 42, in function_name"
_TB_FRAME_RE = re.compile(
    r'^\s*File "(?P<file>[^"]+)", line (?P<line>\d+), in (?P<func>\S+)',
    re.MULTILINE,
)

# assert <actual> == <expected>  (or reversed)
# Covers: assert r.status_code == 404,  assert 404 == r.status_code
_ASSERT_EQ_RE = re.compile(
    r"assert\s+(?P<lhs>.+?)\s*==\s*(?P<rhs>.+)",
)

# "E    assert 200 == 404"  — pytest rewritten assertion
_E_ASSERT_RE = re.compile(
    r"^E\s+assert\s+(?P<actual>.+?)\s*==\s*(?P<expected>.+)",
    re.MULTILINE,
)

# "+  where 200 = <Response [200 OK]>.status_code"
_WHERE_RE = re.compile(
    r"^\s*\+\s+where\s+(?P<val>.+?)\s*=\s*(?P<expr>.+)",
    re.MULTILINE,
)


def parse_pytest(result: TestRunResult) -> TestRunResult:
    """Populate ``result`` with parsed counts and failures from pytest output.

    Mutates *result* in-place and returns it.
    """
    output = result.stdout + "\n" + result.stderr

    # --- counts ---
    summary_match = _SUMMARY_RE.search(output)
    if summary_match:
        summary_text = summary_match.group("summary")
        counts = {k: int(v) for v, k in _COUNT_RE.findall(summary_text)}
        result.passed = counts.get("passed", 0)
        result.failed = counts.get("failed", 0)
        result.skipped = counts.get("skipped", 0)
        # errors count as failures for our purposes
        if "errors" in counts or "error" in counts:
            result.failed = (result.failed or 0) + counts.get(
                "errors", counts.get("error", 0)
            )
        result.total = (result.passed or 0) + (result.failed or 0) + (result.skipped or 0)

    # --- failing test names ---
    failed_names = _FAILED_LINE_RE.findall(output)

    # --- per-failure data from failure blocks ---
    failure_blocks = _split_failure_blocks(output)

    result.failures = []
    for name in failed_names:
        name = name.strip()
        normalized = _normalize_test_name(name)
        block = failure_blocks.get(normalized, "")

        error_text = _pick_error_lines(block) if block else ""
        tb_file, tb_line = _extract_traceback_location(block)
        expected, actual = _extract_expected_actual(block)

        result.failures.append(
            TestFailure(
                name=name,
                error_text=error_text,
                tb_file=tb_file,
                tb_line=tb_line,
                expected_value=expected,
                actual_value=actual,
            )
        )

    return result


# ---------------------------------------------------------------------------
# Traceback extraction
# ---------------------------------------------------------------------------

def extract_traceback_location(block_text: str) -> tuple[Optional[str], Optional[int]]:
    """Public API: extract the innermost non-test-framework traceback frame.

    Returns (file_path, line_number) or (None, None) when not found.
    The file path is as reported by pytest (may be relative or absolute).
    """
    return _extract_traceback_location(block_text)


def _extract_traceback_location(block_text: str) -> tuple[Optional[str], Optional[int]]:
    """Extract innermost app-source frame from a pytest failure block.

    We skip frames that are in site-packages, pytest internals, or the test
    file itself — preferring frames that point into the application source.
    Returns (file, line) or (None, None).
    """
    if not block_text:
        return None, None

    frames = _TB_FRAME_RE.findall(block_text)
    if not frames:
        return None, None

    # frames is a list of (file, line, func) tuples
    # Filter to app source frames (skip pytest internals and site-packages)
    app_frames = [
        (f, int(ln), fn)
        for f, ln, fn in frames
        if not _is_framework_frame(f)
    ]

    if not app_frames:
        # Fall back to any frame
        f, ln, fn = frames[-1]
        return f, int(ln)

    # Return the innermost app frame (last in list = deepest in call stack)
    f, ln, fn = app_frames[-1]
    return f, ln


def _is_framework_frame(filepath: str) -> bool:
    """Return True for frames we want to skip (pytest, stdlib, site-packages)."""
    skip_markers = (
        "site-packages", "_pytest", "pytest", "pluggy",
        "importlib", "_bootstrap", "<frozen",
    )
    fp = filepath.replace("\\", "/")
    return any(m in fp for m in skip_markers)


# ---------------------------------------------------------------------------
# Expected / actual extraction
# ---------------------------------------------------------------------------

def extract_expected_actual(block_text: str) -> tuple[Optional[str], Optional[str]]:
    """Public API: extract expected and actual values from a failure block."""
    return _extract_expected_actual(block_text)


def _extract_expected_actual(block_text: str) -> tuple[Optional[str], Optional[str]]:
    """Extract expected and actual values from pytest assertion output.

    Returns (expected, actual) strings, or (None, None) when not parseable.
    """
    if not block_text:
        return None, None

    # Primary: "E    assert <actual> == <expected>"
    m = _E_ASSERT_RE.search(block_text)
    if m:
        actual = m.group("actual").strip()
        expected = m.group("expected").strip()
        return expected, actual

    return None, None


# ---------------------------------------------------------------------------
# Failure block splitting
# ---------------------------------------------------------------------------

def _split_failure_blocks(output: str) -> dict[str, str]:
    """Split pytest output into per-test failure blocks.

    Returns a mapping of normalized_test_name -> block_text.
    """
    blocks: dict[str, str] = {}

    failures_start = output.find("FAILURES")
    if failures_start == -1:
        return blocks

    failures_text = output[failures_start:]

    block_header_re = re.compile(r"_+\s+(.+?)\s+_+")
    header_matches = list(block_header_re.finditer(failures_text))

    for i, match in enumerate(header_matches):
        raw_name = match.group(1).strip()
        start = match.end()
        end = header_matches[i + 1].start() if i + 1 < len(header_matches) else len(failures_text)
        block_text = failures_text[start:end].strip()
        normalized = _normalize_test_name(raw_name)
        blocks[normalized] = block_text

    return blocks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_test_name(name: str) -> str:
    """Strip file path prefix, keeping only ClassName::test_name.

    Handles both pytest verbose format ("tests/test_app.py::TestFoo::test_name")
    and failure-block header format ("TestFoo.test_name").
    """
    # Replace dot-separated class.method into class::method for comparison
    name = name.replace(".", "::", 1) if "::" not in name else name
    parts = name.split("::")
    if len(parts) >= 2:
        return "::".join(parts[-2:])
    return name


def _pick_error_lines(block_text: str, max_lines: int = 5) -> str:
    """Extract the most useful assertion/error lines from a failure block."""
    lines = block_text.splitlines()
    error_lines: list[str] = []

    for line in lines:
        stripped = line.lstrip()
        # Lines prefixed with "E " are pytest assertion details
        if stripped.startswith("E ") or stripped.startswith("AssertionError"):
            error_lines.append(stripped)
        if len(error_lines) >= max_lines:
            break

    if not error_lines:
        # Fall back: first non-empty lines
        for line in lines:
            if line.strip():
                error_lines.append(line.strip())
            if len(error_lines) >= 3:
                break

    return "\n".join(error_lines)
