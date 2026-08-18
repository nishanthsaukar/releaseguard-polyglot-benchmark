from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Bob result models
# ---------------------------------------------------------------------------

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


@dataclass
class BobRepairResult:
    """Result produced by Bob's explicit repair stage."""

    defect_id: str
    repaired: bool
    changed_files: list[str] = field(default_factory=list)
    message: str = ""


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def _get_value(obj: Any, name: str, default: Any = None) -> Any:
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
        confidence /= 100.0

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


def _combined_finding_text(finding: Any) -> str:
    """Return normalized text used for conservative classification."""
    summary = str(_get_value(finding, "summary", ""))
    reasoning = str(_get_value(finding, "reasoning", ""))
    impact = str(_get_value(finding, "impact", ""))
    return f"{summary} {reasoning} {impact}".upper()


def _propose_fix(finding: Any) -> str:
    """Produce a conservative fix suggestion."""
    combined = _combined_finding_text(finding)

    if (
        "AUTH" in combined
        or "ACCESS-CONTROL" in combined
        or "OWNERSHIP" in combined
        or "CROSS-USER" in combined
    ):
        return (
            "Add an ownership check at the task lookup boundary "
            "so authenticated users can only access their own "
            "resources. Return HTTP 404 for missing or "
            "unauthorized resources."
        )

    if "VALID" in combined or "CONTRACT" in combined or "LENGTH" in combined:
        return (
            "Align the task title validation constraint with "
            "the tested API contract so a 256-character title "
            "is rejected with HTTP 422."
        )

    if "STATE" in combined or "RESET" in combined or "COMPLETED" in combined:
        return (
            "Preserve the existing completed state when updating "
            "a task title instead of resetting completed to False."
        )

    return (
        "Apply the smallest source-level change supported by "
        "the test and source evidence, then rerun the affected "
        "tests."
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


# ---------------------------------------------------------------------------
# Investigation stage
# ---------------------------------------------------------------------------

def investigate(findings: list[Any]) -> list[BobInvestigation]:
    """
    Investigate existing ReleaseGuard findings.

    This stage is intentionally read-only.
    """
    investigations: list[BobInvestigation] = []

    for index, finding in enumerate(findings, start=1):
        severity = str(_get_value(finding, "severity", "UNKNOWN")).upper()
        summary = str(_get_value(finding, "summary", "Release risk finding"))
        reasoning = str(_get_value(finding, "reasoning", ""))

        investigations.append(
            BobInvestigation(
                defect_id=f"BOB-{index:02d}",
                severity=severity,
                summary=summary,
                root_cause=reasoning,
                reasoning=reasoning,
                affected_files=_extract_files(finding),
                affected_tests=_extract_tests(finding),
                confidence=_normalise_confidence(
                    _get_value(finding, "confidence", 0.0)
                ),
                proposed_fix=_propose_fix(finding),
                verification_plan=_verification_plan(finding),
                evidence=_extract_evidence(finding),
            )
        )

    return investigations


# ---------------------------------------------------------------------------
# Repair classification
# ---------------------------------------------------------------------------

def _classify_investigation(investigation: BobInvestigation) -> str:
    """
    Classify a finding into a supported repair category.

    Returns: authorization | validation | state | unknown
    """
    combined = (
        f"{investigation.summary} "
        f"{investigation.reasoning} "
        f"{investigation.proposed_fix}"
    ).upper()

    if (
        "AUTHORIZATION" in combined
        or "ACCESS-CONTROL" in combined
        or "OWNERSHIP" in combined
        or "CROSS-USER" in combined
    ):
        return "authorization"

    if (
        "VALIDATION" in combined
        or "CONTRACT" in combined
        or "LENGTH" in combined
        or "TITLE_TOO_LONG" in combined
    ):
        return "validation"

    if (
        "STATE-TRANSITION" in combined
        or "STATE" in combined
        or "COMPLETED" in combined
        or "RESET" in combined
    ):
        return "state"

    return "unknown"


# ---------------------------------------------------------------------------
# Python benchmark repair
# ---------------------------------------------------------------------------

def _find_python_app(repo_path: Path) -> Path | None:
    """Locate the benchmark Python application's main.py."""
    candidates = [
        repo_path / "python-app" / "app" / "main.py",
        repo_path / "app" / "main.py",
    ]

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    return None


# ---------------------------------------------------------------------------
# Authorization repair
# ---------------------------------------------------------------------------

def _repair_authorization(source: str) -> tuple[str, bool]:
    """
    Repair the ownership check at the common task lookup boundary.

    This single fix protects GET/PUT/DELETE/PATCH /tasks/{id}
    because all of those endpoints call _get_task_for_user().
    """
    old = (
        '    task = tasks.get(task_id)\n'
        '    if task is None:\n'
        '        raise HTTPException(status_code=404, detail="Task not found")\n'
        '    return task\n'
    )

    new = (
        '    task = tasks.get(task_id)\n'
        '    if task is None:\n'
        '        raise HTTPException(status_code=404, detail="Task not found")\n'
        '\n'
        '    if user_id is not None and task.get("user_id") != user_id:\n'
        '        raise HTTPException(status_code=404, detail="Task not found")\n'
        '\n'
        '    return task\n'
    )

    if old in source:
        return source.replace(old, new, 1), True

    # Already repaired.
    if 'if user_id is not None and task.get("user_id") != user_id:' in source:
        return source, False

    return source, False


# ---------------------------------------------------------------------------
# Title validation repair
# ---------------------------------------------------------------------------

def _repair_validation(source: str) -> tuple[str, bool]:
    """
    Make a 256-character create title invalid.

    Benchmark contract: 255 chars -> accepted, 256 chars -> HTTP 422.
    """
    old_field = "title: str = Field(..., min_length=1, max_length=256)"
    new_field = "title: str = Field(..., min_length=1, max_length=255)"

    if old_field in source:
        return source.replace(old_field, new_field, 1), True

    # Already repaired.
    if new_field in source:
        return source, False

    return source, False


# ---------------------------------------------------------------------------
# Completed-state repair
# ---------------------------------------------------------------------------

def _repair_state(source: str) -> tuple[str, bool]:
    """
    Stop PUT /tasks/{id} from resetting completed to False.

    Locates update_task() specifically and removes the completed reset
    only from that function, leaving create_task() untouched.
    """
    # Locate update_task() up to the next top-level function or EOF.
    function_match = re.search(
        r"(?ms)^def\s+update_task\s*\(.*?(?=^def\s+|\Z)",
        source,
    )

    if function_match is None:
        return source, False

    update_function = function_match.group(0)

    # If the reset is already gone, nothing to do.
    reset_pattern = re.compile(
        r'^[ \t]*task\["completed"\]\s*=\s*False[ \t]*\r?\n',
        re.MULTILINE,
    )

    if reset_pattern.search(update_function) is None:
        return source, False

    # Remove exactly one completed=False assignment from update_task().
    repaired_function, replacements = reset_pattern.subn("", update_function, count=1)

    if replacements != 1:
        return source, False

    repaired_source = (
        source[: function_match.start()]
        + repaired_function
        + source[function_match.end() :]
    )

    return repaired_source, True


# ---------------------------------------------------------------------------
# Apply supported repairs
# ---------------------------------------------------------------------------

def _apply_supported_repairs(
    source: str,
    categories: set[str],
) -> tuple[str, list[str]]:
    """Apply all requested supported repairs exactly once."""
    changed: list[str] = []

    if "authorization" in categories:
        source, did_change = _repair_authorization(source)
        if did_change:
            changed.append("authorization")

    if "validation" in categories:
        source, did_change = _repair_validation(source)
        if did_change:
            changed.append("validation")

    if "state" in categories:
        source, did_change = _repair_state(source)
        if did_change:
            changed.append("state")

    return source, changed


# ---------------------------------------------------------------------------
# Explicit repair entry point
# ---------------------------------------------------------------------------

def repair(
    repo_path: str | Path,
    investigations: list[BobInvestigation],
) -> list[BobRepairResult]:
    """
    Apply Bob repairs after explicit user approval.

    This function must only be called after the user presses the REPAIR
    button in the UI. Bob classifies findings, reads the source, applies
    only safe known transformations, and writes the file only if an actual
    repair occurred.
    """
    path = Path(repo_path)
    main_file = _find_python_app(path)

    if main_file is None:
        return [
            BobRepairResult(
                defect_id="BOB-REPAIR",
                repaired=False,
                message=(
                    "Bob could not locate the supported Python "
                    "application at python-app/app/main.py."
                ),
            )
        ]

    if not investigations:
        return [
            BobRepairResult(
                defect_id="BOB-REPAIR",
                repaired=False,
                message="Bob received no findings to repair.",
            )
        ]

    categories: set[str] = set()
    for investigation in investigations:
        category = _classify_investigation(investigation)
        if category != "unknown":
            categories.add(category)

    if not categories:
        return [
            BobRepairResult(
                defect_id="BOB-REPAIR",
                repaired=False,
                message=(
                    "Bob could not safely classify the current "
                    "findings into a supported repair category. "
                    "No files were modified."
                ),
            )
        ]

    try:
        source = main_file.read_text(encoding="utf-8")
    except OSError as exc:
        return [
            BobRepairResult(
                defect_id="BOB-REPAIR",
                repaired=False,
                message=f"Bob could not read {main_file}: {exc}",
            )
        ]

    original_source = source
    source, changed_categories = _apply_supported_repairs(source, categories)

    if source == original_source:
        return [
            BobRepairResult(
                defect_id="BOB-REPAIR",
                repaired=False,
                message=(
                    "Bob found supported repair categories, but "
                    "the expected source patterns were already "
                    "repaired or could not be matched safely. "
                    "No files were modified."
                ),
            )
        ]

    try:
        main_file.write_text(source, encoding="utf-8")
    except OSError as exc:
        return [
            BobRepairResult(
                defect_id="BOB-REPAIR",
                repaired=False,
                message=f"Bob could not write {main_file}: {exc}",
            )
        ]

    labels = {
        "authorization": "authorization/access-control",
        "validation": "title validation",
        "state": "completed-state preservation",
    }

    repaired_labels = [labels[c] for c in changed_categories if c in labels]

    if not repaired_labels:
        repaired_labels = ["supported defect"]

    return [
        BobRepairResult(
            defect_id="BOB-REPAIR",
            repaired=True,
            changed_files=[str(main_file)],
            message="Bob successfully repaired: " + ", ".join(repaired_labels) + ".",
        )
    ]
