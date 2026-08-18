from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from releaseguard.agents.bob import (
    BobInvestigation,
    BobRepairResult,
    investigate,
    repair,
)
from releaseguard.analyzer.rules import analyze
from releaseguard.evidence.collector import collect_evidence
from releaseguard.models.core import RepositoryReport
from releaseguard.policy.policy import decide
from releaseguard.repository.loader import (
    RepositoryLoadError,
    RepositoryWorkspace,
    open_repository_workspace,
)
from releaseguard.runners.runner import run_tests
from releaseguard.scanner.commands import detect_test_command
from releaseguard.scanner.detector import detect_projects


# ============================================================================
# PAGE CONFIG
# ============================================================================

st.set_page_config(
    page_title="ReleaseGuard",
    page_icon="🛡️",
    layout="wide",
)


# ============================================================================
# PIPELINE
# ============================================================================

def build_report(repo_path: str | Path) -> RepositoryReport:
    """
    Run the complete ReleaseGuard pipeline against an existing workspace.

    Pipeline:

        detect
          ↓
        test
          ↓
        collect evidence
          ↓
        analyze
          ↓
        decide

    The workspace is NOT created or destroyed here.
    """

    repo_path = Path(repo_path)

    # ---------------------------------------------------------
    # 1. Detect projects
    # ---------------------------------------------------------

    projects = detect_projects(repo_path)

    # ---------------------------------------------------------
    # 2. Detect test commands
    # ---------------------------------------------------------

    for project in projects:
        detect_test_command(project, repo_path)

    # ---------------------------------------------------------
    # 3. Run tests
    # ---------------------------------------------------------

    raw_runs = [
        run_tests(project, repo_path)
        for project in projects
    ]

    # ---------------------------------------------------------
    # 4. Normalize evidence
    # ---------------------------------------------------------

    runs = collect_evidence(raw_runs)

    # ---------------------------------------------------------
    # 5. Analyze findings
    # ---------------------------------------------------------

    findings = analyze(
        runs,
        repo_path=repo_path,
    )

    # ---------------------------------------------------------
    # 6. Release decision
    # ---------------------------------------------------------

    decision = decide(findings)

    return RepositoryReport(
        repository_path=str(repo_path),
        projects=projects,
        test_runs=runs,
        findings=findings,
        decision=decision,
    )


def scan_repository(
    target: str,
) -> tuple[
    RepositoryWorkspace,
    RepositoryReport,
    list[BobInvestigation],
]:
    """
    Create a persistent temporary repository workspace,
    run ReleaseGuard, then let Bob investigate the findings.
    """

    workspace = open_repository_workspace(target)

    try:
        report = build_report(workspace.path)

        investigations = investigate(
            report.findings
        )

        return (
            workspace,
            report,
            investigations,
        )

    except Exception:
        workspace.cleanup()
        raise


def rerun_after_repair(
    workspace: RepositoryWorkspace,
) -> tuple[
    RepositoryReport,
    list[BobInvestigation],
]:
    """
    After Bob changes the temporary repository:

        modify
          ↓
        retest
          ↓
        re-analyze
          ↓
        re-decide
          ↓
        Bob investigates remaining findings
    """

    report = build_report(
        workspace.path
    )

    investigations = investigate(
        report.findings
    )

    return report, investigations


# ============================================================================
# WORKSPACE MANAGEMENT
# ============================================================================

def cleanup_existing_workspace() -> None:
    """
    Remove the previous temporary repository workspace.
    """

    workspace = st.session_state.get(
        "repository_workspace"
    )

    if isinstance(
        workspace,
        RepositoryWorkspace,
    ):
        try:
            workspace.cleanup()
        except Exception:
            pass

    st.session_state.pop(
        "repository_workspace",
        None,
    )


# ============================================================================
# GENERIC HELPERS
# ============================================================================

def value(
    obj: Any,
    name: str,
    default: Any = None,
) -> Any:
    """
    Read a property from either:
        - dataclass/object
        - dictionary
    """

    if isinstance(obj, dict):
        return obj.get(
            name,
            default,
        )

    return getattr(
        obj,
        name,
        default,
    )


def text(
    value_: Any,
    default: str = "",
) -> str:

    if value_ is None:
        return default

    return str(value_)


def normalise_confidence(
    value_: Any,
) -> float:

    try:
        confidence = float(
            value_
        )
    except (
        TypeError,
        ValueError,
    ):
        return 0.0

    if confidence > 1:
        confidence /= 100.0

    return min(
        max(
            confidence,
            0.0,
        ),
        1.0,
    )


# ============================================================================
# SEVERITY
# ============================================================================

def severity_label(
    severity: Any,
) -> str:

    return (
        str(severity)
        .upper()
        .replace(
            "SEVERITY.",
            "",
        )
    )


def severity_icon(
    severity: Any,
) -> str:

    value_ = severity_label(
        severity
    )

    if "BLOCKER" in value_:
        return "🔴"

    if "HIGH" in value_:
        return "🟠"

    if "MEDIUM" in value_:
        return "🟡"

    if "LOW" in value_:
        return "🔵"

    return "⚪"


# ============================================================================
# TEST METRICS
# ============================================================================

def get_test_counts(
    report: RepositoryReport,
) -> tuple[int, int, int]:

    total_tests = 0
    passed_tests = 0
    failed_tests = 0

    for run in report.test_runs:

        passed = value(
            run,
            "passed",
            0,
        )

        failed = value(
            run,
            "failed",
            0,
        )

        total = value(
            run,
            "total",
            None,
        )

        if total is None:
            total = value(
                run,
                "total_tests",
                0,
            )

        try:
            passed = int(
                passed or 0
            )
        except (
            TypeError,
            ValueError,
        ):
            passed = 0

        try:
            failed = int(
                failed or 0
            )
        except (
            TypeError,
            ValueError,
        ):
            failed = 0

        try:
            total = int(
                total or 0
            )
        except (
            TypeError,
            ValueError,
        ):
            total = 0

        passed_tests += passed
        failed_tests += failed

        if total > 0:
            total_tests += total
        else:
            total_tests += (
                passed + failed
            )

    return (
        total_tests,
        passed_tests,
        failed_tests,
    )


# ============================================================================
# SOURCE EVIDENCE
# ============================================================================

def finding_reasoning(
    finding: Any,
) -> str:

    reasoning = value(
        finding,
        "reasoning",
    )

    if reasoning:
        return str(
            reasoning
        )

    evidence = value(
        finding,
        "evidence",
    )

    if evidence:
        return str(
            evidence
        )

    return ""


def finding_source_evidence(
    finding: Any,
) -> list[Any]:

    return (
        value(
            finding,
            "source_evidence",
            [],
        )
        or []
    )


def render_source_evidence(
    source_evidence: list[Any],
) -> None:

    if not source_evidence:
        return

    with st.expander(
        "🔎 Source evidence"
    ):

        for item in source_evidence:

            available = bool(
                value(
                    item,
                    "available",
                    False,
                )
            )

            file_path = (
                value(
                    item,
                    "source_file",
                )
                or value(
                    item,
                    "file_path",
                )
                or "Unknown file"
            )

            line = (
                value(
                    item,
                    "source_line",
                )
                or value(
                    item,
                    "line",
                )
            )

            line_end = value(
                item,
                "source_line_end",
            )

            function = (
                value(
                    item,
                    "source_function",
                )
                or value(
                    item,
                    "function_name",
                )
            )

            excerpt = value(
                item,
                "source_excerpt",
            )

            location = str(
                file_path
            )

            if line:

                location += (
                    f":{line}"
                )

                if (
                    line_end
                    and line_end != line
                ):
                    location += (
                        f"-{line_end}"
                    )

            if function:
                location += (
                    f" — {function}"
                )

            if not available:
                st.caption(
                    "Source confirmation was not "
                    "available for this item."
                )

            st.markdown(
                f"**{location}**"
            )

            if excerpt:
                st.code(
                    str(excerpt),
                    language="python",
                )

            method = value(
                item,
                "evidence_method",
            )

            if method and method != "none":
                st.caption(
                    f"Evidence method: `{method}`"
                )


# ============================================================================
# FINDING UI
# ============================================================================

def render_finding(
    finding: Any,
) -> None:

    severity = severity_label(
        value(
            finding,
            "severity",
            "UNKNOWN",
        )
    )

    summary = text(
        value(
            finding,
            "summary",
        ),
        "Release risk finding",
    )

    reasoning = finding_reasoning(
        finding
    )

    impact = value(
        finding,
        "impact",
    )

    confidence = normalise_confidence(
        value(
            finding,
            "confidence",
            0.0,
        )
    )

    affected_files = (
        value(
            finding,
            "affected_files",
            [],
        )
        or []
    )

    affected_tests = (
        value(
            finding,
            "affected_tests",
            [],
        )
        or []
    )

    source_evidence = (
        finding_source_evidence(
            finding
        )
    )

    with st.container(
        border=True
    ):

        st.markdown(
            f"### "
            f"{severity_icon(severity)} "
            f"SEVERITY.{severity}"
        )

        st.markdown(
            f"**{summary}**"
        )

        if reasoning:

            st.markdown(
                "**Why ReleaseGuard thinks this:**"
            )

            st.write(
                reasoning
            )

        if impact:

            st.markdown(
                "**Impact:**"
            )

            st.write(
                impact
            )

        st.progress(
            confidence,
            text=(
                f"Confidence: "
                f"{confidence * 100:.0f}%"
            ),
        )

        if affected_files:

            st.markdown(
                "**Affected files:**"
            )

            for path in affected_files:
                st.code(
                    str(path)
                )

        if affected_tests:

            with st.expander(
                f"🧪 Affected tests "
                f"({len(affected_tests)})"
            ):

                for test_name in affected_tests:
                    st.code(
                        str(test_name)
                    )

        render_source_evidence(
            source_evidence
        )


# ============================================================================
# BOB SUPPORT
# ============================================================================

def repair_supported(
    investigation: BobInvestigation,
) -> bool:
    """
    Determine whether Bob's repair implementation supports
    this investigation.

    Current supported benchmark:
        Python app/main.py
    """

    affected_files = (
        investigation.affected_files
        or []
    )

    for file_path in affected_files:

        normalized = (
            str(file_path)
            .replace("\\", "/")
            .lower()
        )

        if normalized.endswith(
            "app/main.py"
        ):
            return True

    combined = (
        f"{investigation.summary or ''} "
        f"{investigation.reasoning or ''} "
        f"{investigation.root_cause or ''}"
    ).lower()

    return (
        "python project" in combined
        and any(
            word in combined
            for word in (
                "authorization",
                "validation",
                "state",
                "completed",
                "ownership",
            )
        )
    )


# ============================================================================
# REPAIR RESULT
# ============================================================================

def render_repair_result(
    result: BobRepairResult,
) -> None:

    if result.repaired:

        st.success(
            f"✅ {result.message}"
        )

        if result.changed_files:

            st.markdown(
                "**Changed files:**"
            )

            for file_path in result.changed_files:
                st.code(
                    str(file_path)
                )

    else:

        st.warning(
            f"⚠️ {result.message}"
        )


# ============================================================================
# BOB REPAIR ACTION
# ============================================================================

def run_bob_repair(
    investigation: BobInvestigation,
) -> None:

    workspace = st.session_state.get(
        "repository_workspace"
    )

    if not isinstance(
        workspace,
        RepositoryWorkspace,
    ):

        st.error(
            "The temporary repository workspace "
            "is no longer available. "
            "Please run a new scan."
        )

        return

    with st.status(
        "Bob is repairing the repository...",
        expanded=True,
    ) as status:

        st.write(
            "🤖 Bob is applying the proposed repair..."
        )

        try:

            # -------------------------------------------------
            # APPLY REPAIR
            # -------------------------------------------------

            results = repair(
                workspace.path,
                [investigation],
            )

            if not results:

                status.update(
                    label="No repair result",
                    state="error",
                    expanded=True,
                )

                st.error(
                    "Bob did not produce a repair result."
                )

                return

            result = results[0]

            render_repair_result(
                result
            )

            if not result.repaired:

                status.update(
                    label="Repair not applied",
                    state="error",
                    expanded=True,
                )

                return

            # -------------------------------------------------
            # RETEST
            # -------------------------------------------------

            st.write(
                "🧪 Bob's change was applied."
            )

            st.write(
                "🔄 Re-running the complete test suite..."
            )

            report, investigations = (
                rerun_after_repair(
                    workspace
                )
            )

            # -------------------------------------------------
            # SAVE NEW STATE
            # -------------------------------------------------

            st.session_state[
                "report"
            ] = report

            st.session_state[
                "bob_investigations"
            ] = investigations

            st.session_state[
                "last_repair_result"
            ] = result

            # -------------------------------------------------
            # VERIFICATION SUMMARY
            # -------------------------------------------------

            total, passed, failed = (
                get_test_counts(report)
            )

            st.write(
                f"🧪 Verification complete: "
                f"{passed}/{total} tests passed."
            )

            if failed == 0:

                st.success(
                    "✅ All tests are passing after Bob's repair."
                )

            else:

                st.error(
                    f"❌ {failed} test(s) are still failing "
                    "after Bob's repair."
                )

            # -------------------------------------------------
            # FINAL STATUS
            # -------------------------------------------------

            if (
                failed == 0
                and not report.findings
            ):

                status.update(
                    label=(
                        "Repair verified — "
                        "Release Ready"
                    ),
                    state="complete",
                    expanded=True,
                )

            elif failed == 0:

                status.update(
                    label=(
                        "Repair verified — "
                        "Review remaining findings"
                    ),
                    state="complete",
                    expanded=True,
                )

            else:

                status.update(
                    label=(
                        "Repair applied — "
                        "verification still failing"
                    ),
                    state="error",
                    expanded=True,
                )

        except Exception as exc:

            status.update(
                label="Repair failed",
                state="error",
                expanded=True,
            )

            st.error(
                "Bob encountered an error "
                "while repairing the repository."
            )

            st.exception(exc)


# ============================================================================
# BOB INVESTIGATION UI
# ============================================================================

def render_bob_investigation(
    investigation: BobInvestigation,
) -> None:

    severity = severity_label(
        investigation.severity
    )

    confidence = normalise_confidence(
        investigation.confidence
    )

    with st.container(
        border=True
    ):

        st.markdown(
            f"### "
            f"{severity_icon(severity)} "
            f"{investigation.defect_id}"
        )

        st.markdown(
            f"**{investigation.summary}**"
        )

        st.caption(
            f"Severity: SEVERITY.{severity} | "
            f"Confidence: "
            f"{confidence * 100:.0f}%"
        )

        st.progress(
            confidence,
            text=(
                f"Confidence: "
                f"{confidence * 100:.0f}%"
            ),
        )

        # -----------------------------------------------------
        # ROOT CAUSE
        # -----------------------------------------------------

        st.markdown(
            "**Root cause:**"
        )

        st.write(
            investigation.root_cause
            or
            "Bob could not establish a more specific root cause."
        )

        # -----------------------------------------------------
        # REASONING
        # -----------------------------------------------------

        st.markdown(
            "**Bob's reasoning:**"
        )

        st.write(
            investigation.reasoning
            or
            "No additional reasoning was produced."
        )

        # -----------------------------------------------------
        # FILES
        # -----------------------------------------------------

        if investigation.affected_files:

            st.markdown(
                "**Affected files:**"
            )

            for path in investigation.affected_files:
                st.code(
                    str(path)
                )

        # -----------------------------------------------------
        # TESTS
        # -----------------------------------------------------

        if investigation.affected_tests:

            st.markdown(
                "**Affected tests:**"
            )

            for test_name in investigation.affected_tests:
                st.code(
                    str(test_name)
                )

        # -----------------------------------------------------
        # EVIDENCE
        # -----------------------------------------------------

        if investigation.evidence:

            with st.expander(
                "🔎 Evidence"
            ):

                for item in investigation.evidence:
                    st.code(
                        str(item)
                    )

        # -----------------------------------------------------
        # PROPOSED FIX
        # -----------------------------------------------------

        st.markdown(
            "**Proposed fix:**"
        )

        st.info(
            investigation.proposed_fix
            or
            "Apply the smallest source-level "
            "change supported by the evidence."
        )

        # -----------------------------------------------------
        # VERIFICATION
        # -----------------------------------------------------

        st.markdown(
            "**Verification plan:**"
        )

        st.write(
            investigation.verification_plan
            or
            "Apply the proposed change, rerun "
            "the affected tests, and confirm that "
            "previously passing tests remain green."
        )

        st.divider()

        # -----------------------------------------------------
        # REPAIR BUTTON
        # -----------------------------------------------------

        if repair_supported(
            investigation
        ):

            repair_clicked = st.button(
                "🔧 REPAIR",
                key=(
                    f"repair_"
                    f"{investigation.defect_id}"
                ),
                type="primary",
                use_container_width=True,
            )

            if repair_clicked:

                run_bob_repair(
                    investigation
                )

        else:

            st.warning(
                "🔒 Automatic repair is not available "
                "for this finding yet."
            )

            st.caption(
                "Bob's current repair implementation "
                "supports the Python benchmark, but "
                "this particular finding is not yet "
                "covered by the repair rules."
            )

        st.caption(
            "Bob investigates findings first. "
            "Repository files are modified only after "
            "the REPAIR action is explicitly selected."
        )


# ============================================================================
# BOB SECTION
# ============================================================================

def render_bob_section(
    investigations: list[BobInvestigation],
) -> None:

    st.divider()

    st.subheader(
        "🤖 Bob Agent"
    )

    st.caption(
        "Bob investigates ReleaseGuard findings, "
        "proposes conservative fixes, and applies "
        "supported repairs only after explicit approval."
    )

    if not investigations:

        st.success(
            "🎉 Bob has no remaining findings to investigate."
        )

        return

    for investigation in investigations:

        render_bob_investigation(
            investigation
        )


# ============================================================================
# RELEASE DECISION
# ============================================================================

def render_decision(
    report: RepositoryReport,
) -> None:

    decision = str(
        report.decision
    ).upper()

    total, passed, failed = (
        get_test_counts(report)
    )

    # ---------------------------------------------------------
    # Strongest condition:
    # Everything passes and no findings remain.
    # ---------------------------------------------------------

    if (
        failed == 0
        and not report.findings
    ):

        st.success(
            "✅ RELEASE READY"
        )

        st.caption(
            f"All {total} tests passed and "
            "no release-risk findings remain."
        )

        return

    # ---------------------------------------------------------
    # Tests failing.
    # ---------------------------------------------------------

    if failed > 0:

        st.error(
            "🚫 RELEASE BLOCKED"
        )

        st.caption(
            f"{failed} test(s) are failing."
        )

        return

    # ---------------------------------------------------------
    # Findings remain even though tests pass.
    # ---------------------------------------------------------

    if "BLOCKED" in decision:

        st.error(
            "🚫 RELEASE BLOCKED"
        )

    elif "REVIEW" in decision:

        st.warning(
            "⚠️ REVIEW REQUIRED"
        )

    else:

        st.info(
            "ℹ️ RELEASE REQUIRES REVIEW"
        )

    st.caption(
        f"{passed}/{total} tests pass, "
        f"but {len(report.findings)} "
        "release-risk finding(s) remain."
    )


# ============================================================================
# METRICS
# ============================================================================

def render_metrics(
    report: RepositoryReport,
) -> None:

    total, passed, failed = (
        get_test_counts(report)
    )

    col1, col2, col3 = st.columns(3)

    with col1:

        st.metric(
            "Tests",
            total,
        )

    with col2:

        st.metric(
            "Passed",
            passed,
        )

    with col3:

        st.metric(
            "Failed",
            failed,
        )


# ============================================================================
# PROJECTS
# ============================================================================

def render_projects(
    report: RepositoryReport,
) -> None:

    st.subheader(
        "Detected projects"
    )

    if not report.projects:

        st.info(
            "No supported projects were detected."
        )

        return

    for project in report.projects:

        language = value(
            project,
            "language",
            "Unknown",
        )

        language_value = value(
            language,
            "value",
            language,
        )

        command = value(
            project,
            "test_command",
        )

        available = value(
            project,
            "test_command_available",
            None,
        )

        left, right = st.columns(
            [2, 5]
        )

        with left:

            st.markdown(
                f"**Language."
                f"{str(language_value).upper()}**"
            )

        with right:

            if command:

                if available is False:

                    st.markdown(
                        f"`{command}` "
                        "· ⚠️ executable unavailable"
                    )

                else:

                    st.markdown(
                        f"`{command}`"
                    )

            else:

                st.caption(
                    "No test command detected."
                )


# ============================================================================
# LAST REPAIR
# ============================================================================

def render_last_repair_result() -> None:

    result = st.session_state.get(
        "last_repair_result"
    )

    if not isinstance(
        result,
        BobRepairResult,
    ):
        return

    st.divider()

    st.subheader(
        "🔧 Last Repair"
    )

    if result.repaired:

        st.success(
            result.message
        )

        if result.changed_files:

            st.markdown(
                "**Files changed by Bob:**"
            )

            for file_path in result.changed_files:

                st.code(
                    str(file_path)
                )

    else:

        st.warning(
            result.message
        )


# ============================================================================
# FINAL REPORT
# ============================================================================

def render_report(
    report: RepositoryReport,
    investigations: list[BobInvestigation],
) -> None:

    # ---------------------------------------------------------
    # Decision
    # ---------------------------------------------------------

    render_decision(
        report
    )

    st.divider()

    # ---------------------------------------------------------
    # Test metrics
    # ---------------------------------------------------------

    render_metrics(
        report
    )

    st.divider()

    # ---------------------------------------------------------
    # Projects
    # ---------------------------------------------------------

    render_projects(
        report
    )

    st.divider()

    # ---------------------------------------------------------
    # Findings
    # ---------------------------------------------------------

    st.subheader(
        f"Findings ({len(report.findings)})"
    )

    if not report.findings:

        st.success(
            "🎉 No release-risk findings were detected."
        )

    else:

        for finding in report.findings:

            render_finding(
                finding
            )

    # ---------------------------------------------------------
    # Bob
    # ---------------------------------------------------------

    render_bob_section(
        investigations
    )

    # ---------------------------------------------------------
    # Last repair
    # ---------------------------------------------------------

    render_last_repair_result()


# ============================================================================
# MAIN
# ============================================================================

def main() -> None:

    # ------------------------------------------------------------------------
    # HEADER
    # ------------------------------------------------------------------------

    st.markdown(
        """
        # 🛡️ ReleaseGuard

        ### Evidence-driven release readiness for GitHub repositories

        Give ReleaseGuard a public GitHub repository.

        It will:

        **clone → detect → test → inspect → reason → decide**

        If Bob identifies a supported defect:

        **REPAIR → modify → retest → verify**
        """
    )

    st.divider()

    # ------------------------------------------------------------------------
    # REPOSITORY INPUT
    # ------------------------------------------------------------------------

    github_url = st.text_input(
        "Public GitHub repository",
        placeholder=(
            "https://github.com/owner/repository"
        ),
        value=st.session_state.get(
            "github_url",
            "",
        ),
    )

    st.session_state[
        "github_url"
    ] = github_url

    # ------------------------------------------------------------------------
    # SCAN BUTTON
    # ------------------------------------------------------------------------

    scan_clicked = st.button(
        "🔎 Scan Repository",
        type="primary",
        use_container_width=True,
    )

    # ------------------------------------------------------------------------
    # SCAN
    # ------------------------------------------------------------------------

    if scan_clicked:

        if not github_url.strip():

            st.warning(
                "Please enter a GitHub repository URL."
            )

            return

        # -----------------------------------------------------
        # Clean previous temporary workspace
        # -----------------------------------------------------

        cleanup_existing_workspace()

        st.session_state.pop(
            "report",
            None,
        )

        st.session_state.pop(
            "bob_investigations",
            None,
        )

        st.session_state.pop(
            "last_repair_result",
            None,
        )

        try:

            with st.status(
                "Running ReleaseGuard...",
                expanded=True,
            ) as status:

                st.write(
                    "📥 Cloning repository..."
                )

                st.write(
                    "🔍 Detecting languages "
                    "and test suites..."
                )

                st.write(
                    "🧪 Running tests..."
                )

                st.write(
                    "🧾 Collecting failure evidence..."
                )

                st.write(
                    "🔎 Inspecting source code..."
                )

                st.write(
                    "🧠 Classifying release risk..."
                )

                st.write(
                    "🤖 Bob is investigating findings..."
                )

                (
                    workspace,
                    report,
                    investigations,
                ) = scan_repository(
                    github_url.strip()
                )

                status.update(
                    label="Scan complete",
                    state="complete",
                    expanded=False,
                )

            # -------------------------------------------------
            # Save workspace
            # -------------------------------------------------

            st.session_state[
                "repository_workspace"
            ] = workspace

            st.session_state[
                "report"
            ] = report

            st.session_state[
                "bob_investigations"
            ] = investigations

        except RepositoryLoadError as exc:

            st.error(
                f"Could not load repository: {exc}"
            )

            return

        except Exception as exc:

            st.error(
                "ReleaseGuard encountered "
                "an unexpected error."
            )

            st.exception(
                exc
            )

            return

    # ------------------------------------------------------------------------
    # CURRENT STATE
    # ------------------------------------------------------------------------

    report = st.session_state.get(
        "report"
    )

    investigations = st.session_state.get(
        "bob_investigations",
        [],
    )

    workspace = st.session_state.get(
        "repository_workspace"
    )

    # ------------------------------------------------------------------------
    # WORKSPACE INFO
    # ------------------------------------------------------------------------

    if isinstance(
        workspace,
        RepositoryWorkspace,
    ):

        st.caption(
            f"Workspace: `{workspace.path}`"
        )

        st.caption(
            "This is a temporary working copy. "
            "Bob repairs this copy rather than your "
            "local source repository."
        )

    # ------------------------------------------------------------------------
    # REPORT
    # ------------------------------------------------------------------------

    if report:

        render_report(
            report,
            investigations,
        )

    elif not scan_clicked:

        st.info(
            "Enter a public GitHub repository URL "
            "and click **Scan Repository**."
        )


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    main()