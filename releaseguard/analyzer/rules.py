"""Deterministic risk-analysis rules for ReleaseGuard v0.2.

Rules operate on TestRunResult evidence and produce Finding objects.
Each finding now includes source evidence (when locatable) and
deterministic reasoning.

Rules must be:
  - deterministic (no randomness, no LLM calls)
  - conservative (prefer lower confidence over false certainty)
  - structured (each rule is a standalone function)
  - honest (never claim source evidence without actually having it)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from releaseguard.models.core import (
    Finding,
    FindingCategory,
    Severity,
    SourceEvidence,
    TestFailure,
    TestRunResult,
)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def analyze(
    test_runs: list[TestRunResult],
    repo_path: Optional[Path] = None,
) -> list[Finding]:
    """Run all deterministic rules against the evidence and return findings."""
    findings: list[Finding] = []
    for run in test_runs:
        findings.extend(_analyze_run(run, repo_path))
    return findings


# ---------------------------------------------------------------------------
# Per-run analysis
# ---------------------------------------------------------------------------

def _analyze_run(run: TestRunResult, repo_path: Optional[Path]) -> list[Finding]:
    findings: list[Finding] = []

    # Tooling / infrastructure findings
    findings.extend(_rule_tooling_unavailable(run))

    if not run.tooling_available:
        return findings

    # A runner can start successfully but fail during collection/import.
    # This is not the same thing as a test case failing.
    findings.extend(_rule_execution_error(run))

    # Test execution findings
    findings.extend(_rule_tests_failed(run))
    findings.extend(_rule_no_tests_found(run))
    findings.extend(_rule_unverified_test_execution(run))

    # Pattern + source-backed findings from failure names
    if run.failures:
        findings.extend(_rule_authorization_failures(run, repo_path))
        findings.extend(_rule_validation_contract_failures(run, repo_path))
        findings.extend(_rule_state_corruption_failures(run, repo_path))

    return findings


# ---------------------------------------------------------------------------
# Rule: tooling unavailable
# ---------------------------------------------------------------------------

def _rule_tooling_unavailable(run: TestRunResult) -> list[Finding]:
    if run.tooling_available:
        return []
    return [
        Finding(
            category=FindingCategory.TOOLING,
            severity=Severity.HIGH,
            title="Test tooling unavailable",
            summary=(
                f"Could not execute '{run.command}' for "
                f"{run.project.language.value} project: {run.unavailable_reason}"
            ),
            evidence=run.unavailable_reason or "",
            confidence=1.0,
        )
    ]


# ---------------------------------------------------------------------------
# Rule: test execution/collection error
# ---------------------------------------------------------------------------

def _rule_execution_error(run: TestRunResult) -> list[Finding]:
    if not run.execution_error:
        return []

    output = (run.stderr or run.stdout or "").strip()
    evidence = run.execution_error
    if output:
        evidence += "\n" + output[:1000]

    return [
        Finding(
            category=FindingCategory.TOOLING,
            severity=Severity.HIGH,
            title=f"Test execution error in {run.project.language.value} project",
            summary=(
                f"The test runner started, but pytest could not complete "
                f"normal test collection/execution: {run.execution_error}."
            ),
            evidence=evidence,
            confidence=1.0,
        )
    ]


# ---------------------------------------------------------------------------
# Rule: any test failures → at minimum a functional finding
# ---------------------------------------------------------------------------

def _rule_tests_failed(run: TestRunResult) -> list[Finding]:
    if not run.has_failures:
        return []

    failed = run.failed or 0
    total = run.total or 0
    passed = run.passed or 0

    # If we have no parsed counts, the exit code alone is insufficient.
    if failed == 0 and total == 0:
        return [
            Finding(
                category=FindingCategory.TESTING,
                severity=Severity.HIGH,
                title=f"Test command exited non-zero in {run.project.language.value} project",
                summary=(
                    f"The test command '{run.command}' exited with code "
                    f"{run.exit_code} but no test counts were parsed. "
                    "Manual inspection required."
                ),
                evidence=(
                    f"exit_code={run.exit_code}\n"
                    + (run.stderr[:500] if run.stderr else "(no stderr captured)")
                ),
                confidence=0.6,
            )
        ]

    failure_names = [f.name for f in run.failures]
    evidence_lines = [f"  - {name}" for name in failure_names[:20]]
    if len(failure_names) > 20:
        evidence_lines.append(f"  ... and {len(failure_names) - 20} more")

    evidence = (
        f"exit_code={run.exit_code}  "
        f"{failed} failed / {passed} passed / {total} total\n"
        + "\n".join(evidence_lines)
    )

    return [
        Finding(
            category=FindingCategory.FUNCTIONAL,
            severity=Severity.BLOCKER,
            title=f"{failed} test(s) failing in {run.project.language.value} project",
            summary=(
                f"{failed} out of {total} tests are failing. "
                "Test failures must be resolved before release."
            ),
            evidence=evidence,
            affected_tests=failure_names,
            confidence=1.0,
        )
    ]


# ---------------------------------------------------------------------------
# Rule: no tests found (zero total)
# ---------------------------------------------------------------------------

def _rule_no_tests_found(run: TestRunResult) -> list[Finding]:
    """Emit a HIGH finding when the command ran but found zero tests (total == 0)."""
    if run.execution_error:
        return []
    if run.total is None or run.total > 0:
        return []
    return [
        Finding(
            category=FindingCategory.TESTING,
            severity=Severity.HIGH,
            title=f"No tests found in {run.project.language.value} project",
            summary="Test command ran successfully but collected zero test cases.",
            evidence=f"command='{run.command}'  exit_code={run.exit_code}  total=0",
            confidence=0.9,
        )
    ]


# ---------------------------------------------------------------------------
# Rule: command succeeded but test counts could not be determined
# ---------------------------------------------------------------------------

def _rule_unverified_test_execution(run: TestRunResult) -> list[Finding]:
    """Emit a HIGH finding when exit_code==0 but total is unknown (None).

    CASE C: command appeared to succeed but no test count was parseable.
    This means we cannot trust that tests actually executed.
    """
    if run.execution_error:
        return []
    if run.exit_code != 0:
        return []
    if run.total is not None:
        return []
    return [
        Finding(
            category=FindingCategory.TESTING,
            severity=Severity.HIGH,
            title=f"Could not verify test execution in {run.project.language.value} project",
            summary=(
                f"The test command '{run.command}' exited successfully (code 0) "
                "but no test count could be determined from the output. "
                "Test execution cannot be verified — release must not proceed."
            ),
            evidence=(
                f"command='{run.command}'  exit_code=0  total=None\n"
                + ((run.stdout or "")[:500] if run.stdout else "(no stdout captured)")
            ),
            confidence=0.9,
        )
    ]


# ---------------------------------------------------------------------------
# Keyword patterns for classification
# ---------------------------------------------------------------------------

_AUTHZ_PATTERNS = re.compile(
    r"(authori[sz]|permission|ownership|wrong.user|other.user|another.user"
    r"|cross.user|forbid|access.control|bypass|privilege|unauthori[sz])",
    re.IGNORECASE,
)

_VALIDATION_PATTERNS = re.compile(
    r"(valid|contract|schema|422|max.length|min.length|too.long|empty.title"
    r"|missing.title|field|constrain|format)",
    re.IGNORECASE,
)

_STATE_PATTERNS = re.compile(
    r"(state|complet|corrupt|reset|transition|flag|idempoten)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Rule: authorization / security failures
# ---------------------------------------------------------------------------

def _rule_authorization_failures(
    run: TestRunResult,
    repo_path: Optional[Path],
) -> list[Finding]:
    matches = [f for f in run.failures if _AUTHZ_PATTERNS.search(f.name)]
    if not matches:
        return []

    names = [f.name for f in matches]

    # Gather source evidence for authorisation failures
    source_evidences = _collect_source_evidence(matches, run, repo_path, "authz")

    # Build evidence text
    evidence = _build_evidence_text(
        f"{len(matches)} authorization-related test(s) failing:",
        matches, source_evidences,
    )

    # Reasoning
    from releaseguard.reasoning.reasoner import reason_authorization
    reasoning = reason_authorization(matches, source_evidences)

    # Confidence: higher when source confirms missing ownership check
    confidence = _compute_confidence_authz(matches, source_evidences)

    # Affected files from source evidence
    affected_files = _extract_affected_files(source_evidences)

    return [
        Finding(
            category=FindingCategory.SECURITY,
            severity=Severity.BLOCKER,
            title="Authorization / access-control test failures detected",
            summary=(
                f"{len(matches)} test(s) with authorization-related names are "
                "failing. This is a strong indicator of an access-control defect "
                "that must be resolved before release."
            ),
            evidence=evidence,
            affected_tests=names,
            affected_files=affected_files,
            confidence=confidence,
            source_evidence=source_evidences,
            reasoning=reasoning,
        )
    ]


# ---------------------------------------------------------------------------
# Rule: validation / API contract failures
# ---------------------------------------------------------------------------

def _rule_validation_contract_failures(
    run: TestRunResult,
    repo_path: Optional[Path],
) -> list[Finding]:
    matches = [f for f in run.failures if _VALIDATION_PATTERNS.search(f.name)]
    if not matches:
        return []

    names = [f.name for f in matches]

    source_evidences = _collect_source_evidence(matches, run, repo_path, "validation")

    # For validation failures, also inspect the payload model's field constraints
    # directly — this surfaces Pydantic class-level max_length / min_length values
    # that are not visible inside the endpoint function body.
    source_evidences = _enrich_validation_with_field_evidence(
        matches, run, repo_path, source_evidences
    )

    evidence = _build_evidence_text(
        f"{len(matches)} validation/contract-related test(s) failing:",
        matches, source_evidences,
    )

    from releaseguard.reasoning.reasoner import reason_validation
    reasoning = reason_validation(matches, source_evidences)

    confidence = _compute_confidence_validation(matches, source_evidences)
    affected_files = _extract_affected_files(source_evidences)

    return [
        Finding(
            category=FindingCategory.API_CONTRACT,
            severity=Severity.HIGH,
            title="API contract / validation test failures detected",
            summary=(
                f"{len(matches)} test(s) with validation/contract-related names "
                "are failing. This may indicate an API contract violation."
            ),
            evidence=evidence,
            affected_tests=names,
            affected_files=affected_files,
            confidence=confidence,
            source_evidence=source_evidences,
            reasoning=reasoning,
        )
    ]


# ---------------------------------------------------------------------------
# Rule: state / data corruption failures
# ---------------------------------------------------------------------------

def _rule_state_corruption_failures(
    run: TestRunResult,
    repo_path: Optional[Path],
) -> list[Finding]:
    matches = [
        f for f in run.failures
        if _STATE_PATTERNS.search(f.name)
        and not _AUTHZ_PATTERNS.search(f.name)
        and not _VALIDATION_PATTERNS.search(f.name)
    ]
    if not matches:
        return []

    names = [f.name for f in matches]

    source_evidences = _collect_source_evidence(matches, run, repo_path, "state")

    evidence = _build_evidence_text(
        f"{len(matches)} state/transition-related test(s) failing:",
        matches, source_evidences,
    )

    from releaseguard.reasoning.reasoner import reason_state_corruption
    reasoning = reason_state_corruption(matches, source_evidences)

    confidence = _compute_confidence_state(matches, source_evidences)
    affected_files = _extract_affected_files(source_evidences)

    return [
        Finding(
            category=FindingCategory.FUNCTIONAL,
            severity=Severity.HIGH,
            title="State-transition / data-integrity test failures detected",
            summary=(
                f"{len(matches)} test(s) with state/transition-related names "
                "are failing. This may indicate data corruption or incorrect "
                "state management."
            ),
            evidence=evidence,
            affected_tests=names,
            affected_files=affected_files,
            confidence=confidence,
            source_evidence=source_evidences,
            reasoning=reasoning,
        )
    ]


# ---------------------------------------------------------------------------
# Source evidence collection
# ---------------------------------------------------------------------------

def _collect_source_evidence(
    failures: list[TestFailure],
    run: TestRunResult,
    repo_path: Optional[Path],
    hint: str,
) -> list[SourceEvidence]:
    """Collect source evidence for a set of related failures."""
    if repo_path is None:
        return []

    from releaseguard.models.core import Language
    if run.project.language != Language.PYTHON:
        return []

    from releaseguard.evidence.linker_impl import link_failures_to_source
    linked = link_failures_to_source(run, repo_path)

    # Only keep evidence relevant to the failures we care about
    failure_set = {id(f) for f in failures}
    evidences: list[SourceEvidence] = []
    seen_funcs: set[str] = set()

    for lf in linked:
        if id(lf.failure) not in failure_set:
            continue
        src = lf.source

        # Attach the inspection result to the SourceEvidence for reasoning use
        if src.available and src.source_function:
            key = f"{src.source_file}:{src.source_function}"
            if key in seen_funcs:
                continue
            seen_funcs.add(key)

            # Enrich with AST inspection for deeper analysis
            src = _enrich_source_evidence(src, run, repo_path, hint)

        evidences.append(src)

    return evidences


# Mapping from test verb prefix → (class_name, field_name) that carries the constraint.
# This lets the analyzer find "TaskCreate.title" directly when the failing test is
# "test_create_title_too_long_returns_422" without guessing from the function body.
_VALIDATION_FIELD_HINTS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"create.*title", re.IGNORECASE), "TaskCreate", "title"),
    (re.compile(r"update.*title", re.IGNORECASE), "TaskUpdate", "title"),
]


def _enrich_validation_with_field_evidence(
    failures: list[TestFailure],
    run: TestRunResult,
    repo_path: Optional[Path],
    existing: list[SourceEvidence],
) -> list[SourceEvidence]:
    """Append class-field level SourceEvidence for validation failures.

    For each validation failure whose name matches a known field-hint pattern,
    inspect the corresponding Pydantic model class field and append a
    SourceEvidence record whose ``source_excerpt`` contains the raw
    ``Field(...)`` annotation and whose ``reasoning`` lists the parsed
    constraints.

    This runs only for Python projects when ``repo_path`` is provided.
    """
    if repo_path is None:
        return existing

    from releaseguard.models.core import Language
    if run.project.language != Language.PYTHON:
        return existing

    from releaseguard.source.inspector import inspect_class_field

    # Find source files to search (same set used for heuristic linking)
    from releaseguard.evidence.linker_impl import _find_app_source_files
    source_files = _find_app_source_files(run, repo_path)

    added: list[SourceEvidence] = []
    seen_keys: set[str] = set()

    for failure in failures:
        test_name = failure.name.split("::")[-1]
        for pattern, class_name, field_name in _VALIDATION_FIELD_HINTS:
            if not pattern.search(test_name):
                continue
            key = f"{class_name}.{field_name}"
            if key in seen_keys:
                break
            # Search all known source files for this class+field
            for source_file in source_files:
                result = inspect_class_field(
                    repo_path=repo_path,
                    source_file=source_file,
                    class_name=class_name,
                    field_name=field_name,
                )
                if not result.available:
                    continue
                seen_keys.add(key)
                # Format constraints as a human-readable note
                constraint_str = ", ".join(
                    f"{k}={v}" for k, v in sorted(result.field_constraints.items())
                )
                reasoning = (
                    f"Class {class_name}.{field_name} found in {source_file} "
                    f"at line {result.source_line}."
                )
                if constraint_str:
                    reasoning += f" Field constraints: {constraint_str}."
                added.append(
                    SourceEvidence(
                        available=True,
                        source_file=source_file,
                        source_function=None,
                        source_line=result.source_line,
                        source_excerpt=result.source_excerpt,
                        evidence_method="ast",
                        reasoning=reasoning,
                    )
                )
                break  # found in this file; stop searching
            break  # pattern matched; move to next failure

    return existing + added


def _enrich_source_evidence(
    src: SourceEvidence,
    run: TestRunResult,
    repo_path: Path,
    hint: str,
) -> SourceEvidence:
    """Run deeper AST analysis and attach inspection result to SourceEvidence."""
    if not src.available or not src.source_file or not src.source_function:
        return src

    from releaseguard.source.inspector import inspect_source
    insp = inspect_source(
        repo_path=repo_path,
        source_file=src.source_file,
        function_name=src.source_function,
    )

    if insp.available:
        src.source_excerpt = insp.source_excerpt
        src.source_line = insp.start_line
        src.source_line_end = insp.end_line
        # Stash inspection for reasoning layer
        src._inspection_result = insp  # type: ignore[attr-defined]

    return src


# ---------------------------------------------------------------------------
# Confidence helpers
# ---------------------------------------------------------------------------

def _compute_confidence_authz(
    failures: list[TestFailure],
    evidences: list[SourceEvidence],
) -> float:
    base = 0.85
    available = [s for s in evidences if s.available]

    if not available:
        return base

    # Boost confidence when source evidence shows no ownership check
    for src in available:
        insp = getattr(src, "_inspection_result", None)
        if insp is not None and not insp.has_ownership_check:
            base = min(base + 0.10, 0.97)
        elif src.source_excerpt:
            # Check excerpt for ownership pattern
            has_check = any(
                t in (src.source_excerpt or "")
                for t in ("user_id !=", "!= user_id", "task[\"user_id\"]", "task['user_id']")
            )
            if not has_check:
                base = min(base + 0.07, 0.95)

    return round(base, 2)


def _compute_confidence_validation(
    failures: list[TestFailure],
    evidences: list[SourceEvidence],
) -> float:
    base = 0.75
    available = [s for s in evidences if s.available]

    if available and any(s.source_excerpt for s in available):
        base = min(base + 0.10, 0.90)

    # Boost if expected/actual values are available
    if any(f.expected_value and f.actual_value for f in failures):
        base = min(base + 0.05, 0.92)

    return round(base, 2)


def _compute_confidence_state(
    failures: list[TestFailure],
    evidences: list[SourceEvidence],
) -> float:
    base = 0.75
    available = [s for s in evidences if s.available]

    if available and any(s.source_excerpt for s in available):
        # Boost if 'completed' assignment found in source
        for src in available:
            if src.source_excerpt and "completed" in src.source_excerpt:
                import re
                if re.search(r"completed.*=.*False|=.*False.*completed", src.source_excerpt):
                    base = min(base + 0.15, 0.92)
                    break

    return round(base, 2)


# ---------------------------------------------------------------------------
# Evidence text helpers
# ---------------------------------------------------------------------------

def _build_evidence_text(
    header: str,
    failures: list[TestFailure],
    evidences: list[SourceEvidence],
) -> str:
    """Build a combined evidence string from test + source evidence."""
    lines = [header]
    for f in failures:
        lines.append(f"  - {f.name}")

    # First failure assertion detail
    snippets = [f.error_text for f in failures if f.error_text]
    if snippets:
        lines.append("")
        lines.append("First assertion failure:")
        lines.append(snippets[0])

    # Source evidence summary
    available_src = [s for s in evidences if s.available]
    if available_src:
        lines.append("")
        lines.append("Source evidence:")
        for src in available_src[:2]:
            fn = src.source_function or "(unknown)"
            sf = src.source_file or "(unknown)"
            linfo = f" line {src.source_line}" if src.source_line else ""
            lines.append(f"  {fn}() in {sf}{linfo}  [via {src.evidence_method}]")
    else:
        lines.append("")
        lines.append("Source evidence: not located (test evidence only)")

    return "\n".join(lines)


def _extract_affected_files(evidences: list[SourceEvidence]) -> list[str]:
    """Extract unique source file paths from evidence list."""
    files: list[str] = []
    for src in evidences:
        if src.available and src.source_file and src.source_file not in files:
            files.append(src.source_file)
    return files
