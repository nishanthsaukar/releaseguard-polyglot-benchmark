"""Regression tests for the Node.js GitHub repository test execution pipeline.

Covers:
  1. Node dependency installation: npm ci when package-lock.json exists
  2. Node dependency installation: npm install when only package.json exists
  3. Node dependency installation failure → finding produced, no READY
  4. Non-zero npm test with unknown/unparseable output → HIGH finding
  5. exit_code 0 with total None → HIGH finding
  6. exit_code 0 with total 0 → HIGH finding
  7. Valid Node built-in test output parses correctly
  8. Valid Mocha output parses correctly
  9. A successful Node project can still become READY
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from releaseguard.models.core import (
    FindingCategory,
    Language,
    ProjectInfo,
    ReleaseDecision,
    Severity,
    TestRunResult,
)
from releaseguard.analyzer.rules import analyze
from releaseguard.parsers.node_parser import parse_node
from releaseguard.policy.policy import decide


# ===========================================================================
# Helpers
# ===========================================================================

def _node_project(test_command: str = "npm test", evidence_files: list[str] | None = None) -> ProjectInfo:
    return ProjectInfo(
        language=Language.NODE,
        confidence=0.9,
        test_command=test_command,
        test_command_available=True,
        evidence_files=evidence_files or [],
    )


def _run(
    exit_code: int = 0,
    stdout: str = "",
    stderr: str = "",
    total: int | None = None,
    passed: int | None = None,
    failed: int | None = None,
    skipped: int | None = None,
) -> TestRunResult:
    return TestRunResult(
        project=_node_project(),
        command="npm test",
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_seconds=0.5,
        total=total,
        passed=passed,
        failed=failed,
        skipped=skipped,
    )


# ===========================================================================
# 1 & 2.  Node dependency installation — npm ci vs npm install
# ===========================================================================

class TestNodeDependencyInstallation:
    """npm ci is used when package-lock.json exists; npm install otherwise."""

    def _make_pkg_json(self, path: Path) -> None:
        (path / "package.json").write_text(
            json.dumps({"scripts": {"test": "node --test"}}),
            encoding="utf-8",
        )

    def test_npm_ci_used_when_package_lock_exists(self, tmp_path):
        """When package-lock.json is present, the install command is npm ci."""
        from releaseguard.runners.runner import _install_node_deps

        self._make_pkg_json(tmp_path)
        (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")

        proj = _node_project()
        captured_cmd = []

        def _fake_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            r = MagicMock()
            r.returncode = 0
            r.stdout = ""
            r.stderr = ""
            return r

        with patch("releaseguard.runners.runner.subprocess.run", side_effect=_fake_run):
            result = _install_node_deps(tmp_path, proj)

        assert result is None, "Successful install should return None"
        # The install command should contain 'ci'
        assert "ci" in captured_cmd, f"Expected 'npm ci' but got: {captured_cmd}"

    def test_npm_install_used_when_no_package_lock(self, tmp_path):
        """When only package.json exists, the install command is npm install."""
        from releaseguard.runners.runner import _install_node_deps

        self._make_pkg_json(tmp_path)
        # No package-lock.json

        proj = _node_project()
        captured_cmd = []

        def _fake_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            r = MagicMock()
            r.returncode = 0
            r.stdout = ""
            r.stderr = ""
            return r

        with patch("releaseguard.runners.runner.subprocess.run", side_effect=_fake_run):
            result = _install_node_deps(tmp_path, proj)

        assert result is None, "Successful install should return None"
        assert "install" in captured_cmd, f"Expected 'npm install' but got: {captured_cmd}"

    def test_no_package_json_skips_install(self, tmp_path):
        """If there is no package.json at all, installation is skipped (returns None)."""
        from releaseguard.runners.runner import _install_node_deps

        proj = _node_project()

        with patch("releaseguard.runners.runner.subprocess.run") as mock_run:
            result = _install_node_deps(tmp_path, proj)

        mock_run.assert_not_called()
        assert result is None


# ===========================================================================
# 3.  Dependency installation failure → finding produced, no READY
# ===========================================================================

class TestNodeInstallationFailureBlocksRelease:
    """A failed npm ci/install must produce a TOOLING finding and block READY."""

    def _make_pkg_lock(self, path: Path) -> None:
        (path / "package.json").write_text(
            json.dumps({"scripts": {"test": "node --test"}}),
            encoding="utf-8",
        )
        (path / "package-lock.json").write_text("{}", encoding="utf-8")

    def test_install_failure_returns_unavailable_result(self, tmp_path):
        """When npm ci exits non-zero, _install_node_deps returns a TestRunResult."""
        from releaseguard.runners.runner import _install_node_deps

        self._make_pkg_lock(tmp_path)
        proj = _node_project()

        def _fake_run(cmd, **kwargs):
            r = MagicMock()
            r.returncode = 1
            r.stdout = ""
            r.stderr = "npm ERR! code ENOLOCK"
            return r

        with patch("releaseguard.runners.runner.subprocess.run", side_effect=_fake_run):
            result = _install_node_deps(tmp_path, proj)

        assert result is not None
        assert result.unavailable_reason is not None
        assert "fail" in result.unavailable_reason.lower()

    def test_install_failure_produces_tooling_finding(self, tmp_path):
        """A failed npm ci must produce a HIGH TOOLING finding."""
        from releaseguard.runners.runner import _install_node_deps

        self._make_pkg_lock(tmp_path)
        proj = _node_project()

        def _fake_run(cmd, **kwargs):
            r = MagicMock()
            r.returncode = 1
            r.stdout = ""
            r.stderr = "npm ERR! code ENOLOCK"
            return r

        with patch("releaseguard.runners.runner.subprocess.run", side_effect=_fake_run):
            failed_result = _install_node_deps(tmp_path, proj)

        assert failed_result is not None
        findings = analyze([failed_result])
        tooling_findings = [f for f in findings if f.category == FindingCategory.TOOLING]
        assert tooling_findings, "Installation failure must produce a TOOLING finding"
        assert any(f.severity in (Severity.HIGH, Severity.BLOCKER) for f in tooling_findings)

    def test_install_failure_blocks_ready(self, tmp_path):
        """RELEASE READY must never be returned after dependency installation fails."""
        from releaseguard.runners.runner import _install_node_deps

        self._make_pkg_lock(tmp_path)
        proj = _node_project()

        def _fake_run(cmd, **kwargs):
            r = MagicMock()
            r.returncode = 1
            r.stdout = ""
            r.stderr = "npm ERR! code ENOLOCK"
            return r

        with patch("releaseguard.runners.runner.subprocess.run", side_effect=_fake_run):
            failed_result = _install_node_deps(tmp_path, proj)

        assert failed_result is not None
        findings = analyze([failed_result])
        decision = decide(findings)
        assert decision != ReleaseDecision.READY, (
            f"Release must not be READY after dependency installation failure. "
            f"Got {decision} with findings: {findings}"
        )

    def test_install_timeout_returns_unavailable_result(self, tmp_path):
        """When npm ci times out, _install_node_deps returns a TestRunResult."""
        import subprocess
        from releaseguard.runners.runner import _install_node_deps

        self._make_pkg_lock(tmp_path)
        proj = _node_project()

        with patch(
            "releaseguard.runners.runner.subprocess.run",
            side_effect=subprocess.TimeoutExpired(["npm", "ci"], 300),
        ):
            result = _install_node_deps(tmp_path, proj)

        assert result is not None
        assert result.unavailable_reason is not None
        assert "timed out" in result.unavailable_reason.lower()


# ===========================================================================
# 4.  Non-zero npm test with unknown/unparseable output → HIGH finding
# ===========================================================================

class TestNonZeroExitWithUnknownOutput:
    """CASE A: exit_code != 0, total=None, failed=None → must produce HIGH finding."""

    def test_non_zero_exit_no_parseable_output_produces_high_finding(self):
        run = _run(exit_code=1, stdout="", stderr="Error: Cannot find module './test'")
        # No parsing → total, passed, failed all remain None
        findings = analyze([run])
        high_or_blocker = [f for f in findings if f.severity in (Severity.HIGH, Severity.BLOCKER)]
        assert high_or_blocker, (
            "Non-zero exit with unverifiable output must produce HIGH or BLOCKER finding"
        )

    def test_non_zero_exit_no_output_produces_high_finding(self):
        run = _run(exit_code=1, stdout="", stderr="")
        findings = analyze([run])
        high_or_blocker = [f for f in findings if f.severity in (Severity.HIGH, Severity.BLOCKER)]
        assert high_or_blocker, "Non-zero exit with no output must produce a significant finding"

    def test_non_zero_exit_unknown_output_is_not_ready(self):
        run = _run(exit_code=1, stdout="some unrecognized output", stderr="")
        findings = analyze([run])
        decision = decide(findings)
        assert decision != ReleaseDecision.READY, (
            "READY must not be returned when exit_code != 0 and test counts are unknown"
        )

    def test_non_zero_exit_finding_category_is_testing(self):
        run = _run(exit_code=1, stderr="Error: Cannot find module './test'")
        findings = analyze([run])
        testing_findings = [
            f for f in findings
            if f.category == FindingCategory.TESTING
            and f.severity in (Severity.HIGH, Severity.BLOCKER)
        ]
        assert testing_findings, "Must emit a TESTING category finding for unverifiable non-zero exit"

    def test_non_zero_exit_evidence_contains_exit_code(self):
        run = _run(exit_code=2, stderr="something went wrong")
        findings = analyze([run])
        high_findings = [f for f in findings if f.severity in (Severity.HIGH, Severity.BLOCKER)]
        assert high_findings
        assert any("2" in f.evidence for f in high_findings), (
            "Exit code should appear in finding evidence"
        )


# ===========================================================================
# 5.  exit_code 0 with total None → HIGH finding (CASE C)
# ===========================================================================

class TestExitZeroTotalNone:
    """CASE C: exit_code == 0, total == None → must produce HIGH finding."""

    def test_exit_zero_total_none_produces_high_finding(self):
        run = _run(exit_code=0, stdout="some output that doesn't match any parser")
        # total remains None
        assert run.total is None
        findings = analyze([run])
        high_or_blocker = [f for f in findings if f.severity in (Severity.HIGH, Severity.BLOCKER)]
        assert high_or_blocker, (
            "exit_code=0 with total=None must produce HIGH or BLOCKER finding"
        )

    def test_exit_zero_total_none_is_not_ready(self):
        run = _run(exit_code=0, stdout="unexpected output format")
        findings = analyze([run])
        decision = decide(findings)
        assert decision != ReleaseDecision.READY, (
            "READY must not be returned when exit_code=0 but test count is unknown"
        )

    def test_exit_zero_total_none_finding_is_testing_category(self):
        run = _run(exit_code=0, stdout="unrecognized output")
        findings = analyze([run])
        testing_high = [
            f for f in findings
            if f.category == FindingCategory.TESTING
            and f.severity in (Severity.HIGH, Severity.BLOCKER)
        ]
        assert testing_high, "Must emit a TESTING HIGH finding for unverifiable zero exit"


# ===========================================================================
# 6.  exit_code 0 with total 0 → HIGH finding (CASE B)
# ===========================================================================

class TestExitZeroTotalZero:
    """CASE B: exit_code == 0, total == 0 → must produce HIGH finding."""

    def test_exit_zero_total_zero_produces_high_finding(self):
        run = _run(exit_code=0, total=0, passed=0, failed=0)
        findings = analyze([run])
        high_or_blocker = [f for f in findings if f.severity in (Severity.HIGH, Severity.BLOCKER)]
        assert high_or_blocker, (
            "exit_code=0 with total=0 must produce HIGH or BLOCKER finding"
        )

    def test_exit_zero_total_zero_is_not_ready(self):
        run = _run(exit_code=0, total=0, passed=0, failed=0)
        findings = analyze([run])
        decision = decide(findings)
        assert decision != ReleaseDecision.READY, (
            "READY must not be returned when zero tests were found"
        )

    def test_exit_zero_total_zero_finding_is_testing_category(self):
        run = _run(exit_code=0, total=0, passed=0, failed=0)
        findings = analyze([run])
        testing_findings = [
            f for f in findings if f.category == FindingCategory.TESTING
        ]
        assert testing_findings, "No tests found must emit a TESTING finding"


# ===========================================================================
# 7.  Node built-in test runner output parses correctly
# ===========================================================================

class TestNodeBuiltinParser:
    """Node built-in (node:test) output should parse into structured counts."""

    def test_all_passing(self):
        stderr = textwrap.dedent("""\
            ℹ tests 5
            ℹ pass 5
            ℹ fail 0
            ℹ skipped 0
        """)
        run = _run(exit_code=0, stderr=stderr)
        result = parse_node(run)
        assert result.total == 5
        assert result.passed == 5
        assert result.failed == 0
        assert result.skipped == 0

    def test_with_failures(self):
        stderr = textwrap.dedent("""\
            not ok 1 - myTest fails
            ℹ tests 3
            ℹ pass 2
            ℹ fail 1
        """)
        run = _run(exit_code=1, stderr=stderr)
        result = parse_node(run)
        assert result.total == 3
        assert result.passed == 2
        assert result.failed == 1
        assert len(result.failures) >= 1

    def test_plain_format_all_pass(self):
        stdout = textwrap.dedent("""\
            ok 1 - first test
            ok 2 - second test
            tests 2
            pass 2
            fail 0
        """)
        run = _run(exit_code=0, stdout=stdout)
        result = parse_node(run)
        assert result.total == 2
        assert result.passed == 2
        assert result.failed == 0

    def test_no_recognisable_output_leaves_counts_none(self):
        run = _run(exit_code=0, stdout="some random output")
        result = parse_node(run)
        assert result.total is None
        assert result.passed is None
        assert result.failed is None


# ===========================================================================
# 8.  Mocha output parses correctly
# ===========================================================================

class TestMochaParser:
    """Mocha output should parse into structured totals."""

    def test_mocha_passing_only(self):
        stdout = "  100 passing (500ms)\n"
        run = _run(exit_code=0, stdout=stdout)
        result = parse_node(run)
        assert result.passed == 100
        assert result.failed == 0
        assert result.total == 100

    def test_mocha_passing_and_failing(self):
        stdout = "  100 passing (500ms)\n  2 failing\n"
        run = _run(exit_code=1, stdout=stdout)
        result = parse_node(run)
        assert result.passed == 100
        assert result.failed == 2
        assert result.total == 102

    def test_mocha_with_pending(self):
        stdout = "  50 passing (300ms)\n  3 pending\n  1 failing\n"
        run = _run(exit_code=1, stdout=stdout)
        result = parse_node(run)
        assert result.passed == 50
        assert result.failed == 1
        assert result.skipped == 3
        assert result.total == 54

    def test_mocha_failure_name_extracted(self):
        stdout = textwrap.dedent("""\
              5 passing
              1 failing

              1) Suite name > should handle edge case
        """)
        run = _run(exit_code=1, stdout=stdout)
        result = parse_node(run)
        assert result.failed == 1
        assert result.failures
        assert "Suite name" in result.failures[0].name or "edge case" in result.failures[0].name

    def test_mocha_failing_produces_blocker_finding(self):
        stdout = "  5 passing (100ms)\n  2 failing\n"
        run = _run(exit_code=1, stdout=stdout)
        result = parse_node(run)
        assert result.failed == 2
        assert result.total == 7
        findings = analyze([result])
        blocker_findings = [f for f in findings if f.severity == Severity.BLOCKER]
        assert blocker_findings, "Known failing tests must produce a BLOCKER finding"


# ===========================================================================
# 9.  A successful Node project can still become READY
# ===========================================================================

class TestSuccessfulNodeProjectCanBeReady:
    """When all tests pass and counts are known, the decision should be READY."""

    def test_all_passing_with_known_counts_is_ready(self):
        run = _run(exit_code=0, total=20, passed=20, failed=0)
        findings = analyze([run])
        decision = decide(findings)
        assert decision == ReleaseDecision.READY, (
            f"All-green Node project should be READY, got {decision} with findings: {findings}"
        )

    def test_all_passing_mocha_output_is_ready(self):
        stdout = "  42 passing (1234ms)\n"
        run = _run(exit_code=0, stdout=stdout)
        result = parse_node(run)
        assert result.total == 42
        assert result.failed == 0
        findings = analyze([result])
        decision = decide(findings)
        assert decision == ReleaseDecision.READY, (
            f"Passing Mocha output should produce READY, got {decision}"
        )

    def test_all_passing_node_builtin_output_is_ready(self):
        stderr = "ℹ tests 10\nℹ pass 10\nℹ fail 0\n"
        run = _run(exit_code=0, stderr=stderr)
        result = parse_node(run)
        assert result.total == 10
        assert result.failed == 0
        findings = analyze([result])
        decision = decide(findings)
        assert decision == ReleaseDecision.READY, (
            f"Passing Node built-in output should produce READY, got {decision}"
        )
