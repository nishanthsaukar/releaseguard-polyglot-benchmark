"""Human-readable report renderer for the CLI."""

from __future__ import annotations

from releaseguard.models.core import (
    Finding,
    FindingCategory,
    Language,
    ProjectInfo,
    ReleaseDecision,
    RepositoryReport,
    Severity,
    TestRunResult,
)

_DIVIDER = "-" * 50


def render_report(report: RepositoryReport) -> str:
    """Return the full CLI report as a string."""
    lines: list[str] = []

    lines.append("")
    lines.append("ReleaseGuard")
    lines.append(_DIVIDER)
    lines.append("")
    lines.append(f"Repository: {report.repository_path}")
    lines.append("")

    # --- Languages / Projects ---
    lines.append("Languages detected:")
    if report.projects:
        for proj in report.projects:
            cmd_status = _format_command_status(proj)
            lines.append(f"  {proj.language.value}{cmd_status}")
    else:
        lines.append("  (none detected)")
    lines.append("")

    # --- Test runs ---
    lines.append("Tests:")
    if report.test_runs:
        for run in report.test_runs:
            lines.extend(_format_test_run(run))
    else:
        lines.append("  (no test commands executed)")
    lines.append("")

    # --- Findings ---
    lines.append("Findings:")
    if report.findings:
        for finding in _sort_findings(report.findings):
            lines.extend(_format_finding(finding))
    else:
        lines.append("  No findings — all checks passed.")
    lines.append("")

    # --- Decision ---
    lines.append(_DIVIDER)
    lines.append("")
    lines.append(f"RELEASE: {report.decision.value}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_command_status(proj: ProjectInfo) -> str:
    if proj.test_command is None:
        return ""
    available = proj.test_command_available
    if available is True:
        return f"  (test: {proj.test_command})"
    if available is False:
        return f"  (test: {proj.test_command}  [tool not on PATH])"
    return f"  (test: {proj.test_command})"


def _format_test_run(run: TestRunResult) -> list[str]:
    lines = []
    lang = run.project.language.value

    if not run.tooling_available:
        lines.append(f"  [{lang}] SKIPPED — {run.unavailable_reason}")
        return lines

    # Counts
    if run.total is not None:
        passed_str = f"{run.passed or 0} passed"
        failed_str = f"{run.failed or 0} failed"
        skipped_str = (
            f", {run.skipped} skipped" if run.skipped else ""
        )
        duration = f"{run.duration_seconds:.1f}s"
        lines.append(
            f"  [{lang}] {passed_str}, {failed_str}{skipped_str}  ({duration})"
        )
    else:
        status = "passed" if run.exit_code == 0 else f"FAILED (exit {run.exit_code})"
        lines.append(f"  [{lang}] {status}  ({run.duration_seconds:.1f}s)")

    return lines


def _format_finding(finding: Finding) -> list[str]:
    lines = []
    sev = finding.severity.value
    title = finding.title
    lines.append(f"  [{sev}] {title}")
    lines.append(f"  Summary:  {finding.summary}")

    # Test evidence
    for ev_line in finding.evidence.splitlines():
        lines.append(f"  Evidence: {ev_line}")

    # Source evidence
    available_src = [s for s in finding.source_evidence if s.available]
    if available_src:
        lines.append(f"  Source evidence ({len(available_src)} location(s)):")
        for src in available_src[:2]:
            fn = src.source_function or "(unknown)"
            sf = src.source_file or "(unknown)"
            linfo = f":{src.source_line}" if src.source_line else ""
            lines.append(f"    File: {sf}{linfo}  function: {fn}()  [via {src.evidence_method}]")
            if src.source_excerpt:
                # Show a compact excerpt (first 6 lines)
                excerpt_lines = src.source_excerpt.splitlines()[:6]
                for el in excerpt_lines:
                    lines.append(f"    | {el}")
                if len(src.source_excerpt.splitlines()) > 6:
                    lines.append(f"    | ... ({len(src.source_excerpt.splitlines()) - 6} more lines)")

    # Root-cause reasoning
    if finding.reasoning:
        lines.append("  Reasoning:")
        for r_line in finding.reasoning.splitlines():
            lines.append(f"    {r_line}")

    # Affected files
    if finding.affected_files:
        lines.append(f"  Affected files: {', '.join(finding.affected_files[:3])}")

    if finding.affected_tests:
        shown = finding.affected_tests[:5]
        lines.append(f"  Affected tests ({len(finding.affected_tests)}):")
        for t in shown:
            lines.append(f"    - {t}")
        if len(finding.affected_tests) > 5:
            lines.append(f"    ... and {len(finding.affected_tests) - 5} more")

    conf_pct = int(finding.confidence * 100)
    lines.append(f"  Confidence: {conf_pct}%")
    lines.append("")
    return lines


def _sort_findings(findings: list[Finding]) -> list[Finding]:
    """Sort findings from most to least severe."""
    order = {
        Severity.BLOCKER: 0,
        Severity.HIGH: 1,
        Severity.MEDIUM: 2,
        Severity.LOW: 3,
        Severity.INFO: 4,
    }
    return sorted(findings, key=lambda f: order.get(f.severity, 99))
