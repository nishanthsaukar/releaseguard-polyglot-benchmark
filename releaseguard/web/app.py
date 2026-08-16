from __future__ import annotations

import streamlit as st
from pathlib import Path

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


def scan_repository(target: str) -> RepositoryReport:
    """
    Run the same ReleaseGuard pipeline used by the CLI,
    but expose the result to the web UI.
    """
    with load_repository(target) as repo_path:
        repo_path = Path(repo_path)

        # 1. Detect languages/projects
        projects = detect_projects(repo_path)

        # 2. Detect test commands
        for project in projects:
            detect_test_command(project, repo_path)

        # 3. Execute tests
        raw_runs = [
            run_tests(project, repo_path)
            for project in projects
        ]

        # 4. Parse/enrich evidence
        runs = collect_evidence(raw_runs)

        # 5. Analyze source + test evidence
        findings = analyze(
            runs,
            repo_path=repo_path,
        )

        # 6. Release decision
        decision = decide(findings)

        return RepositoryReport(
            repository_path=str(repo_path),
            projects=projects,
            test_runs=runs,
            findings=findings,
            decision=decision,
        )


def severity_icon(severity) -> str:
    value = str(severity).upper()

    if "BLOCKER" in value:
        return "🔴"

    if "HIGH" in value:
        return "🟠"

    if "MEDIUM" in value:
        return "🟡"

    return "🔵"


def render_finding(finding) -> None:
    severity = str(finding.severity).upper()

    with st.container(border=True):
        st.markdown(
            f"### {severity_icon(finding.severity)} {severity}"
        )

        st.markdown(
            f"**{finding.summary}**"
        )

        if getattr(finding, "reasoning", None):
            st.markdown("**Why ReleaseGuard thinks this:**")
            st.write(finding.reasoning)

        if getattr(finding, "impact", None):
            st.markdown("**Impact:**")
            st.write(finding.impact)

        confidence = getattr(finding, "confidence", None)

        if confidence is not None:
            st.progress(
                min(max(float(confidence), 0.0), 1.0),
                text=f"Confidence: {float(confidence) * 100:.0f}%",
            )

        affected_files = getattr(finding, "affected_files", None)

        if affected_files:
            st.markdown("**Affected files:**")
            for path in affected_files:
                st.code(str(path))

        evidence = getattr(finding, "source_evidence", None)

        if evidence:
            with st.expander("🔎 Source evidence"):
                for item in evidence:
                    file_path = getattr(item, "file_path", None)
                    line = getattr(item, "line", None)
                    function = getattr(item, "function_name", None)
                    excerpt = getattr(item, "source_excerpt", None)

                    location = str(file_path or "Unknown")

                    if line:
                        location += f":{line}"

                    if function:
                        location += f" — {function}"

                    st.markdown(f"**{location}**")

                    if excerpt:
                        st.code(excerpt, language="python")


def render_report(report: RepositoryReport) -> None:
    decision = str(report.decision).upper()

    if "BLOCKED" in decision:
        st.error("🚫 RELEASE BLOCKED")
    elif "REVIEW" in decision:
        st.warning("⚠️ REVIEW REQUIRED")
    else:
        st.success("✅ RELEASE READY")

    st.divider()

    col1, col2, col3 = st.columns(3)

    total_tests = 0
    passed_tests = 0
    failed_tests = 0

    for run in report.test_runs:
        total_tests += getattr(run, "total_tests", 0) or 0
        passed_tests += getattr(run, "passed", 0) or 0
        failed_tests += getattr(run, "failed", 0) or 0

    with col1:
        st.metric(
            "Tests",
            total_tests,
        )

    with col2:
        st.metric(
            "Passed",
            passed_tests,
        )

    with col3:
        st.metric(
            "Failed",
            failed_tests,
        )

    st.divider()

    st.subheader("Detected projects")

    for project in report.projects:
        language = getattr(project, "language", "Unknown")
        command = getattr(project, "test_command", None)

        st.write(
            f"**{language}**"
            + (
                f" — `{command}`"
                if command
                else ""
            )
        )

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
        placeholder=(
            "https://github.com/owner/repository"
        ),
    )

    scan_clicked = st.button(
        "🔍 Scan Repository",
        type="primary",
        use_container_width=True,
    )

    if not scan_clicked:
        st.info(
            "Enter a public GitHub repository URL and click "
            "**Scan Repository**."
        )
        return

    if not github_url.strip():
        st.warning(
            "Please enter a GitHub repository URL."
        )
        return

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

            report = scan_repository(
                github_url.strip()
            )

            status.update(
                label="Scan complete",
                state="complete",
                expanded=False,
            )

        st.session_state["report"] = report

    except RepositoryLoadError as exc:
        st.error(
            f"Could not load repository: {exc}"
        )
        return

    except Exception as exc:
        st.exception(exc)
        return

    report = st.session_state.get("report")

    if report:
        render_report(report)


if __name__ == "__main__":
    main()