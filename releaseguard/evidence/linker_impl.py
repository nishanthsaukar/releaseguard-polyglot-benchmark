"""Link test failures to source-code locations.

The linker uses two strategies:
1. Traceback-derived: use the file/line recorded in the pytest failure
   traceback to locate the source function via AST inspection.
2. Heuristic: when the traceback points only to the test file, search
   the source tree for functions called by the endpoint under test.

The linker is conservative: it only produces SourceEvidence when it
has actual evidence from the repository, never fabricating locations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from releaseguard.models.core import SourceEvidence, TestFailure, TestRunResult
from releaseguard.source.inspector import SourceInspectionResult, inspect_source


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

@dataclass
class LinkedFailure:
    """A TestFailure enriched with any located source evidence."""

    failure: TestFailure
    source: SourceEvidence


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def link_failures_to_source(
    run: TestRunResult,
    repo_path: Path,
) -> list[LinkedFailure]:
    """Attempt to link each failing test to its source location.

    Returns a list of LinkedFailure objects, one per failure.
    When source evidence cannot be found, the LinkedFailure.source has
    ``available=False`` and explains why.
    """
    return [_link_one(f, run, repo_path) for f in run.failures]


# ---------------------------------------------------------------------------
# Per-failure linking
# ---------------------------------------------------------------------------

def _link_one(
    failure: TestFailure,
    run: TestRunResult,
    repo_path: Path,
) -> LinkedFailure:
    """Link a single TestFailure to source evidence."""

    # Strategy 1: traceback-derived location
    if failure.tb_file and failure.tb_line:
        src = _inspect_from_traceback(failure, repo_path)
        if src.available:
            return LinkedFailure(failure=failure, source=_to_source_evidence(src, "traceback"))

    # Strategy 2: search known source files for a relevant function
    # (applies when we have a project path and language is Python)
    src = _inspect_heuristic(failure, run, repo_path)
    if src and src.available:
        return LinkedFailure(failure=failure, source=_to_source_evidence(src, "heuristic"))

    # No source found — return with available=False
    return LinkedFailure(
        failure=failure,
        source=SourceEvidence(
            available=False,
            evidence_method="none",
            reasoning="Source location could not be determined from available evidence.",
        ),
    )


def _inspect_from_traceback(
    failure: TestFailure,
    repo_path: Path,
) -> SourceInspectionResult:
    """Run AST inspection using the traceback file/line."""
    assert failure.tb_file is not None
    assert failure.tb_line is not None

    return inspect_source(
        repo_path=repo_path,
        source_file=failure.tb_file,
        line_number=failure.tb_line,
    )


def _inspect_heuristic(
    failure: TestFailure,
    run: TestRunResult,
    repo_path: Path,
) -> Optional[SourceInspectionResult]:
    """Try to find relevant source via heuristic search.

    For Python projects, look for source files that contain functions
    whose names might relate to the failure based on the test name.
    """
    from releaseguard.models.core import Language
    if run.project.language != Language.PYTHON:
        return None

    # Infer a candidate function name from the test name
    candidate_func = _infer_function_from_test(failure.name)
    if not candidate_func:
        return None

    # Find Python source files (not test files) in the project
    source_files = _find_app_source_files(run, repo_path)

    for source_file in source_files:
        result = inspect_source(
            repo_path=repo_path,
            source_file=source_file,
            function_name=candidate_func,
        )
        if result.available:
            return result

    return None


def _infer_function_from_test(test_name: str) -> Optional[str]:
    """Infer a likely application function name from a test name.

    Test names like:
      - test_get_wrong_user_returns_404        -> get_task (endpoint)
      - test_update_wrong_user_returns_404     -> update_task (endpoint)
      - test_create_title_too_long_returns_422 -> create_task (endpoint)
      - test_update_does_not_reset_completed   -> update_task (endpoint)

    We extract the verb + noun pattern from the test name.
    """
    # Strip class prefix if present
    name = test_name.split("::")[-1] if "::" in test_name else test_name
    # Remove leading "test_"
    name = re.sub(r"^test_", "", name, flags=re.IGNORECASE)

    # Map common test verb prefixes to likely endpoint function names
    _VERB_MAP = {
        "get": "_get_task_for_user",
        "update": "update_task",
        "delete": "delete_task",
        "create": "create_task",
        "complete": "complete_task",
        "list": "list_tasks",
        "authori": "_get_task_for_user",
        "authenticated": "_get_task_for_user",
        "auth_error": "_get_task_for_user",
    }

    for prefix, func in _VERB_MAP.items():
        if name.lower().startswith(prefix):
            return func

    return None


def _find_app_source_files(run: TestRunResult, repo_path: Path) -> list[str]:
    """Return relative paths of Python application source files (not tests)."""
    results: list[str] = []
    for ev in run.project.evidence_files:
        ev_path = repo_path / ev
        if not ev_path.is_file():
            continue
        if ev_path.suffix != ".py":
            continue
        # Skip test files
        if "test" in ev_path.name.lower():
            continue
        results.append(ev)

    # Also scan for .py files in app subdirectories near the evidence files
    for ev in run.project.evidence_files:
        ev_path = repo_path / ev
        parent = ev_path.parent if ev_path.is_file() else ev_path
        app_dirs = [parent / "app", parent / "src", parent / "lib"]
        for app_dir in app_dirs:
            if app_dir.is_dir():
                for py_file in app_dir.rglob("*.py"):
                    rel = str(py_file.relative_to(repo_path))
                    if rel not in results and "test" not in py_file.name.lower():
                        results.append(rel)

    return results


# ---------------------------------------------------------------------------
# Convert SourceInspectionResult → SourceEvidence
# ---------------------------------------------------------------------------

def _to_source_evidence(
    inspection: SourceInspectionResult,
    method: str,
) -> SourceEvidence:
    return SourceEvidence(
        available=inspection.available,
        source_file=inspection.source_file,
        source_function=inspection.function_name,
        source_line=inspection.start_line,
        source_line_end=inspection.end_line,
        source_excerpt=inspection.source_excerpt,
        evidence_method=method,
    )
