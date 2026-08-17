from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from releaseguard.agents.bob import BobInvestigation, investigate
from releaseguard.analyzer.rules import analyze
from releaseguard.evidence.collector import collect_evidence
from releaseguard.models.core import RepositoryReport
from releaseguard.policy.policy import decide
from releaseguard.repository.loader import RepositoryLoadError, load_repository
from releaseguard.runners.runner import run_tests
from releaseguard.scanner.commands import detect_test_command
from releaseguard.scanner.detector import detect_projects


st.set_page_config(
    page_title="ReleaseGuard",
    page_icon="🛡️",
    layout="wide",
)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def scan_repository(
    target: str,
) -> tuple[RepositoryReport, list[BobInvestigation]]:
    """
    Run the ReleaseGuard pipeline and then run Bob as a read-only
    investigation layer over the resulting findings.

    Bob never modifies the scanned repository.
    """
    with load_repository(target) as repo_path:
        repo_path = Path(repo_path)

        # 1. Detect projects/languages.
        projects = detect_projects(repo_path)

        # 2. Detect the appropriate test command for each project.
        for project in projects:
            detect_test_command(project, repo_path)

        # 3. Run tests.
        raw_runs = [
            run_tests(project, repo_path)
            for project in projects
        ]

        # 4. Normalize test output into structured evidence.
        runs = collect_evidence(raw_runs)

        # 5. Analyze test + source evidence.
        findings = analyze(
            runs,
            repo_path=repo_path,
        )

        # 6. Decide release readiness.
        decision = decide(findings)

        report = RepositoryReport(
            repository_path=str(repo_path),
            projects=projects,
            test_runs=runs,
            findings=findings,
            decision=decision,
        )

        # 7. Bob investigates existing findings.
        #    This is intentionally read-only.
        bob_investigations = investigate(findings)

        return report, bob_investigations


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _value(obj: Any, name: str, default: Any = None) -> Any:
    """Read a field from either a dataclass/object or a dictionary."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _normalise_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0

    if confidence > 1:
        confidence /= 100.0

    return min(max(confidence, 0.0), 1.0)


def severity_icon(severity: Any) -> str:
    value = str(severity).upper()

    if "BLOCKER" in value:
        return "🔴"
    if "HIGH" in value:
        return "🟠"
    if "MEDIUM" in value:
        return "🟡"
    if "LOW" in value:
        return "🔵"

    return "⚪"


def severity_label(severity: Any) -> str:
    value = str(severity).upper()
    return value.replace("SEVERITY.", "")


def _get_test_counts(
    report: RepositoryReport,
) -> tuple[int, int, int]:
    """
    Support both the current TestRunResult model (`total`) and older
    local versions that may expose `total_tests`.
    """
    total_tests = 0
    passed_tests = 0
    failed_tests = 0

    for run in report.test_runs:
        passed = _value(run, "passed", 0) or 0
        failed = _value(run, "failed", 0) or 0

        reported_total = _value(run, "total", None)
        if reported_total is None:
            reported_total = _value(run, "total_tests", 0)

        try:
            passed = int(passed)
        except (TypeError, ValueError):
            passed = 0

        try:
            failed = int(failed)
        except (TypeError, ValueError):
            failed = 0

        try:
            reported_total = int(reported_total or 0)
        except (TypeError, ValueError):
            reported_total = 0

        passed_tests += passed
        failed_tests += failed

        if reported_total > 0:
            total_tests += reported_total
        else:
            total_tests += passed + failed

    return total_tests, passed_tests, failed_tests


def _finding_reasoning(finding: Any) -> str:
    reasoning = _value(finding, "reasoning")
    if reasoning:
        return str(reasoning)

    evidence = _value(finding, "evidence")
    return str(evidence) if evidence else ""


def _finding_source_evidence(finding: Any) -> list[Any]:
    return _value(finding, "source_evidence", []) or []


def _render_source_evidence(
    source_evidence: list[Any],
) -> None:
    if not source_evidence:
        return

    with st.expander("🔎 Source evidence"):
        for item in source_evidence:
            available = bool(_value(item, "available", False))

            file_path = (
                _value(item, "source_file")
                or _value(item, "file_path")
                or "Unknown file"
            )

            line = (
                _value(item, "source_line")
                or _value(item, "line")
            )

            line_end = _value(item, "source_line_end")
            function = (
                _value(item, "source_function")
                or _value(item, "function_name")
            )
            excerpt = _value(item, "source_excerpt")

            location = str(file_path)

            if line:
                location += f":{line}"
                if line_end and line_end != line:
                    location += f"-{line_end}"

            if function:
                location += f" — {function}"

            if not available:
                st.caption(
                    "Source confirmation was not available for this item."
                )

            st.markdown(f"**{location}**")

            if excerpt:
                st.code(
                    str(excerpt),
                    language="python",
                )

            method = _value(item, "evidence_method")
            if method and method != "none":
                st.caption(f"Evidence method: `{method}`")


# ---------------------------------------------------------------------------
# Finding UI
# ---------------------------------------------------------------------------

def render_finding(finding: Any) -> None:
    severity = severity_label(_value(finding, "severity", "UNKNOWN"))
    summary = _text(
        _value(finding, "summary"),
        "Release risk finding",
    )
    reasoning = _finding_reasoning(finding)
    impact = _value(finding, "impact")
    confidence = _normalise_confidence(
        _value(finding, "confidence", 0.0)
    )

    affected_files = _value(finding, "affected_files", []) or []
    affected_tests = _value(finding, "affected_tests", []) or []
    source_evidence = _finding_source_evidence(finding)

    with st.container(border=True):
        st.markdown(
            f"### {severity_icon(severity)} SEVERITY.{severity}"
        )

        st.markdown(f"**{summary}**")

        if reasoning:
            st.markdown("**Why ReleaseGuard thinks this:**")
            st.write(reasoning)

        if impact:
            st.markdown("**Impact:**")
            st.write(impact)

        st.progress(
            confidence,
            text=f"Confidence: {confidence * 100:.0f}%",
        )

        if affected_files:
            st.markdown("**Affected files:**")
            for path in affected_files:
                st.code(str(path))

        if affected_tests:
            with st.expander(
                f"🧪 Affected tests ({len(affected_tests)})"
            ):
                for test_name in affected_tests:
                    st.code(str(test_name))

        _render_source_evidence(source_evidence)


# ---------------------------------------------------------------------------
# Bob UI
# ---------------------------------------------------------------------------

def render_bob_investigation(
    investigation: BobInvestigation,
) -> None:
    severity = severity_label(investigation.severity)
    confidence = _normalise_confidence(investigation.confidence)

    with st.container(border=True):
        st.markdown(
            f"### {severity_icon(severity)} {investigation.defect_id}"
        )

        st.markdown(
            f"**{investigation.summary}**"
        )

        st.caption(
            f"Severity: SEVERITY.{severity} | "
            f"Confidence: {confidence * 100:.0f}%"
        )

        st.progress(
            confidence,
            text=f"Confidence: {confidence * 100:.0f}%",
        )

        st.markdown("**Root cause:**")
        st.write(
            investigation.root_cause
            or "Bob could not establish a more specific root cause."
        )

        st.markdown("**Bob's reasoning:**")
        st.write(
            investigation.reasoning
            or "No additional reasoning was produced."
        )

        if investigation.affected_files:
            st.markdown("**Affected files:**")
            for path in investigation.affected_files:
                st.code(str(path))

        if investigation.affected_tests:
            st.markdown("**Affected tests:**")
            for test_name in investigation.affected_tests:
                st.code(str(test_name))

        if investigation.evidence:
            with st.expander("🔎 Evidence"):
                for item in investigation.evidence:
                    st.code(str(item))

        st.markdown("**Proposed fix:**")
        st.info(
            investigation.proposed_fix
            or "Apply the smallest source-level change supported by the evidence."
        )

        st.markdown("**Verification plan:**")
        st.write(
            investigation.verification_plan
            or "Rerun the affected tests and confirm that previously passing tests remain green."
        )

        st.caption(
            "Bob is read-only. No repository files were modified."
        )


def render_bob_section(
    investigations: list[BobInvestigation],
) -> None:
    st.divider()
    st.subheader("🤖 Bob Agent Investigations")

    st.caption(
        "Bob investigates ReleaseGuard findings using existing test and "
        "source evidence. Bob does not modify repository files."
    )

    if not investigations:
        st.info(
            "Bob has no findings to investigate."
        )
        return

    for investigation in investigations:
        render_bob_investigation(investigation)


# ---------------------------------------------------------------------------
# Report UI
# ---------------------------------------------------------------------------

def render_decision(report: RepositoryReport) -> None:
    decision = str(report.decision).upper()

    if "BLOCKED" in decision:
        st.error("🚫 RELEASE BLOCKED")
    elif "REVIEW" in decision:
        st.warning("⚠️ REVIEW REQUIRED")
    else:
        st.success("✅ RELEASE READY")


def render_metrics(
    report: RepositoryReport,
) -> None:
    total, passed, failed = _get_test_counts(report)

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Tests", total)

    with col2:
        st.metric("Passed", passed)

    with col3:
        st.metric("Failed", failed)


def render_projects(
    report: RepositoryReport,
) -> None:
    st.subheader("Detected projects")

    if not report.projects:
        st.info("No supported projects were detected.")
        return

    for project in report.projects:
        language = _value(
            _value(project, "language"),
            "value",
            _value(project, "language", "Unknown"),
        )

        command = _value(project, "test_command")
        available = _value(
            project,
            "test_command_available",
            None,
        )

        left, right = st.columns([2, 5])

        with left:
            st.markdown(f"**Language.{str(language).upper()}**")

        with right:
            if command:
                if available is False:
                    st.markdown(
                        f"`{command}`  ·  ⚠️ executable unavailable"
                    )
                else:
                    st.markdown(f"`{command}`")
            else:
                st.caption("No test command detected.")


def render_report(
    report: RepositoryReport,
    investigations: list[BobInvestigation],
) -> None:
    render_decision(report)

    st.divider()
    render_metrics(report)

    st.divider()
    render_projects(report)

    st.divider()
    st.subheader(
        f"Findings ({len(report.findings)})"
    )

    if not report.findings:
        st.success(
            "No release-risk findings were detected."
        )
    else:
        for finding in report.findings:
            render_finding(finding)

    render_bob_section(investigations)


# ---------------------------------------------------------------------------
# Main page
# ---------------------------------------------------------------------------

def main() -> None:
    st.markdown(
        """
        # 🛡️ ReleaseGuard

        ### Evidence-driven release readiness for GitHub repositories

        Give ReleaseGuard a public GitHub repository.

        It will **clone → detect → test → inspect → reason → decide**.
        """
    )

    st.divider()

    github_url = st.text_input(
        "Public GitHub repository",
        placeholder="https://github.com/owner/repository",
        value=st.session_state.get(
            "github_url",
            "",
        ),
    )

    st.session_state["github_url"] = github_url

    scan_clicked = st.button(
        "🔎 Scan Repository",
        type="primary",
        use_container_width=True,
    )

    if scan_clicked:
        if not github_url.strip():
            st.warning(
                "Please enter a GitHub repository URL."
            )
            return

        # Clear the previous result before a new scan.
        st.session_state.pop("report", None)
        st.session_state.pop("bob_investigations", None)

        try:
            with st.status(
                "Running ReleaseGuard...",
                expanded=True,
            ) as status:
                st.write("📥 Cloning repository...")
                st.write("🔍 Detecting languages and test suites...")
                st.write("🧪 Running tests...")
                st.write("🧾 Collecting failure evidence...")
                st.write("🔎 Inspecting source code...")
                st.write("🧠 Classifying release risk...")
                st.write("🤖 Bob is investigating findings...")

                report, bob_investigations = scan_repository(
                    github_url.strip()
                )

                status.update(
                    label="Scan complete",
                    state="complete",
                    expanded=False,
                )

            st.session_state["report"] = report
            st.session_state["bob_investigations"] = (
                bob_investigations
            )

        except RepositoryLoadError as exc:
            st.error(
                f"Could not load repository: {exc}"
            )
            return

        except Exception as exc:
            st.error(
                "ReleaseGuard encountered an unexpected error."
            )
            st.exception(exc)
            return

    report = st.session_state.get("report")
    investigations = st.session_state.get(
        "bob_investigations",
        [],
    )

    if report:
        render_report(
            report,
            investigations,
        )
    elif not scan_clicked:
        st.info(
            "Enter a public GitHub repository URL and click "
            "**Scan Repository**."
        )


if __name__ == "__main__":
    main()