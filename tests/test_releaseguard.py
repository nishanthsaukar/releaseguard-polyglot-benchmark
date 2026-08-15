"""Unit tests for ReleaseGuard.

These tests exercise:
  - Language detection
  - Test-command detection
  - Pytest result parsing
  - Risk classification rules
  - Release decision policy

They do NOT modify or reference any benchmark application code.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from releaseguard.models.core import (
    FindingCategory,
    Language,
    ProjectInfo,
    ReleaseDecision,
    Severity,
    TestFailure,
    TestRunResult,
)
from releaseguard.analyzer.rules import analyze
from releaseguard.parsers.pytest_parser import parse_pytest
from releaseguard.policy.policy import decide
from releaseguard.scanner.commands import detect_test_command


# ===========================================================================
# 1.  Language detection
# ===========================================================================

class TestLanguageDetection:
    """Test that detect_projects correctly identifies languages from file layout."""

    def _make_repo(self, tmp_path: Path, files: list[str]) -> Path:
        for rel in files:
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("# placeholder")
        return tmp_path

    def test_detects_python_from_requirements(self, tmp_path):
        from releaseguard.scanner.detector import detect_projects
        self._make_repo(tmp_path, ["requirements.txt", "src/app.py"])
        projects = detect_projects(tmp_path)
        langs = [p.language for p in projects]
        assert Language.PYTHON in langs

    def test_detects_python_from_pyproject(self, tmp_path):
        from releaseguard.scanner.detector import detect_projects
        self._make_repo(tmp_path, ["pyproject.toml"])
        projects = detect_projects(tmp_path)
        langs = [p.language for p in projects]
        assert Language.PYTHON in langs

    def test_detects_rust_from_cargo(self, tmp_path):
        from releaseguard.scanner.detector import detect_projects
        self._make_repo(tmp_path, ["Cargo.toml", "src/main.rs"])
        projects = detect_projects(tmp_path)
        langs = [p.language for p in projects]
        assert Language.RUST in langs

    def test_detects_go_from_go_mod(self, tmp_path):
        from releaseguard.scanner.detector import detect_projects
        self._make_repo(tmp_path, ["go.mod", "main.go"])
        projects = detect_projects(tmp_path)
        langs = [p.language for p in projects]
        assert Language.GO in langs

    def test_detects_node_from_package_json(self, tmp_path):
        from releaseguard.scanner.detector import detect_projects
        p = tmp_path / "package.json"
        p.write_text('{"name": "test"}')
        projects = detect_projects(tmp_path)
        langs = [p.language for p in projects]
        assert Language.NODE in langs

    def test_detects_java_from_pom(self, tmp_path):
        from releaseguard.scanner.detector import detect_projects
        self._make_repo(tmp_path, ["pom.xml", "src/Main.java"])
        projects = detect_projects(tmp_path)
        langs = [p.language for p in projects]
        assert Language.JAVA in langs

    def test_empty_repo_returns_nothing(self, tmp_path):
        from releaseguard.scanner.detector import detect_projects
        projects = detect_projects(tmp_path)
        assert projects == []

    def test_polyglot_repo_detects_multiple(self, tmp_path):
        from releaseguard.scanner.detector import detect_projects
        self._make_repo(tmp_path, [
            "python-app/requirements.txt",
            "go-app/go.mod",
            "node-app/package.json",
        ])
        # Write valid package.json
        (tmp_path / "node-app" / "package.json").write_text('{"name": "x"}')
        projects = detect_projects(tmp_path)
        langs = {p.language for p in projects}
        assert Language.PYTHON in langs
        assert Language.GO in langs
        assert Language.NODE in langs

    def test_python_confidence_high_with_definitive_file(self, tmp_path):
        from releaseguard.scanner.detector import detect_projects
        self._make_repo(tmp_path, ["requirements.txt"])
        projects = detect_projects(tmp_path)
        py = next(p for p in projects if p.language == Language.PYTHON)
        assert py.confidence >= 0.8

    def test_node_modules_not_counted_as_node_project(self, tmp_path):
        """node_modules directory should be skipped."""
        from releaseguard.scanner.detector import detect_projects
        self._make_repo(tmp_path, [
            "python-app/requirements.txt",
            "python-app/node_modules/some_lib/package.json",
        ])
        projects = detect_projects(tmp_path)
        langs = {p.language for p in projects}
        # Node should NOT be detected because the only package.json is inside node_modules
        assert Language.NODE not in langs


# ===========================================================================
# 2.  Test-command detection
# ===========================================================================

class TestCommandDetection:
    """Test that the correct test command is selected per language."""

    def _project(self, lang: Language) -> ProjectInfo:
        return ProjectInfo(language=lang, confidence=0.9)

    def test_python_command_is_pytest(self, tmp_path):
        proj = self._project(Language.PYTHON)
        detect_test_command(proj, tmp_path)
        assert proj.test_command == "pytest"

    def test_rust_command_is_cargo_test(self, tmp_path):
        proj = self._project(Language.RUST)
        detect_test_command(proj, tmp_path)
        assert proj.test_command == "cargo test"

    def test_go_command_is_go_test(self, tmp_path):
        proj = self._project(Language.GO)
        detect_test_command(proj, tmp_path)
        assert proj.test_command == "go test ./..."

    def test_node_command_is_npm_test(self, tmp_path):
        proj = self._project(Language.NODE)
        detect_test_command(proj, tmp_path)
        assert proj.test_command == "npm test"

    def test_java_maven_command_when_pom_exists(self, tmp_path):
        pom = tmp_path / "pom.xml"
        pom.write_text("<project/>")
        proj = self._project(Language.JAVA)
        detect_test_command(proj, tmp_path)
        assert proj.test_command == "mvn test"

    def test_java_gradle_command_when_build_gradle_exists(self, tmp_path):
        gradle = tmp_path / "build.gradle"
        gradle.write_text("// gradle")
        proj = self._project(Language.JAVA)
        detect_test_command(proj, tmp_path)
        assert proj.test_command == "gradle test"

    def test_pytest_available_when_pytest_on_path(self, tmp_path):
        proj = self._project(Language.PYTHON)
        with patch("shutil.which", return_value="/usr/bin/pytest"):
            detect_test_command(proj, tmp_path)
        assert proj.test_command_available is True

    def test_pytest_unavailable_when_not_on_path(self, tmp_path):
        proj = self._project(Language.PYTHON)
        with patch("shutil.which", return_value=None):
            detect_test_command(proj, tmp_path)
        assert proj.test_command_available is False


# ===========================================================================
# 3.  Pytest result parsing
# ===========================================================================

class TestPytestParser:
    """Test the pytest stdout parser."""

    def _run(self, stdout: str, exit_code: int = 0) -> TestRunResult:
        proj = ProjectInfo(language=Language.PYTHON, confidence=0.9)
        result = TestRunResult(
            project=proj,
            command="pytest -v",
            exit_code=exit_code,
            stdout=stdout,
            stderr="",
            duration_seconds=1.0,
        )
        return parse_pytest(result)

    def test_all_passed(self):
        stdout = textwrap.dedent("""\
            collected 69 items

            tests/test_app.py::TestHealth::test_health_returns_200 PASSED
            tests/test_app.py::TestHealth::test_health_body PASSED

            ========================= 69 passed in 0.98s =========================
        """)
        r = self._run(stdout, exit_code=0)
        assert r.passed == 69
        assert r.failed == 0
        assert r.total == 69
        assert r.failures == []

    def test_some_failed(self):
        stdout = textwrap.dedent("""\
            collected 69 items

            tests/test_app.py::TestFoo::test_bar PASSED
            tests/test_app.py::TestAuthorizationFailures::test_authenticated_user_cannot_read_other_task FAILED

            ========================= 58 passed, 11 failed in 1.23s =========================
        """)
        r = self._run(stdout, exit_code=1)
        assert r.passed == 58
        assert r.failed == 11
        assert r.total == 69

    def test_failed_test_names_extracted(self):
        stdout = textwrap.dedent("""\
            FAILED tests/test_app.py::TestFoo::test_broken
            FAILED tests/test_app.py::TestBar::test_also_broken

            ========================= 2 failed, 5 passed in 0.5s =========================
        """)
        r = self._run(stdout, exit_code=1)
        names = [f.name for f in r.failures]
        assert "tests/test_app.py::TestFoo::test_broken" in names
        assert "tests/test_app.py::TestBar::test_also_broken" in names

    def test_skipped_counted(self):
        stdout = textwrap.dedent("""\
            ========================= 10 passed, 2 skipped in 0.5s =========================
        """)
        r = self._run(stdout)
        assert r.skipped == 2
        assert r.passed == 10
        assert r.total == 12

    def test_empty_output_no_crash(self):
        r = self._run("", exit_code=1)
        # No counts extracted, but should not raise
        assert r.total is None or r.total == 0

    def test_single_failure_counts(self):
        stdout = textwrap.dedent("""\
            FAILED tests/test_app.py::TestCreate::test_create_title_too_long_returns_422

            ========================= 1 failed, 68 passed in 1.10s =========================
        """)
        r = self._run(stdout, exit_code=1)
        assert r.failed == 1
        assert r.passed == 68
        assert len(r.failures) == 1

    def test_error_text_extracted_from_failure_block(self):
        stdout = textwrap.dedent("""\
            FAILED tests/test_app.py::TestFoo::test_bar

            ================================= FAILURES =================================
            _________________ TestFoo.test_bar _________________

            def test_bar():
                assert response.status_code == 422
            E   AssertionError: assert 201 == 422

            ========================= 1 failed in 0.5s =========================
        """)
        r = self._run(stdout, exit_code=1)
        assert r.failures
        assert "AssertionError" in r.failures[0].error_text or "422" in r.failures[0].error_text


# ===========================================================================
# 4.  Risk classification rules
# ===========================================================================

class TestRiskClassification:
    """Test that the analyzer correctly classifies findings."""

    def _run_with_failures(self, failure_names: list[str], exit_code: int = 1) -> TestRunResult:
        proj = ProjectInfo(language=Language.PYTHON, confidence=0.9)
        failures = [TestFailure(name=n) for n in failure_names]
        return TestRunResult(
            project=proj,
            command="pytest -v",
            exit_code=exit_code,
            stdout="",
            stderr="",
            duration_seconds=1.0,
            total=len(failure_names) + 5,
            passed=5,
            failed=len(failure_names),
            failures=failures,
        )

    def test_authorization_failures_produce_security_blocker(self):
        run = self._run_with_failures([
            "TestAuthorizationFailures::test_authenticated_user_cannot_read_other_task",
            "TestGetTask::test_get_wrong_user_returns_404",
        ])
        findings = analyze([run])
        security = [f for f in findings if f.category == FindingCategory.SECURITY]
        assert security, "Expected a security finding"
        assert any(f.severity == Severity.BLOCKER for f in security)

    def test_validation_failures_produce_api_contract_finding(self):
        run = self._run_with_failures([
            "TestCreateTask::test_create_title_too_long_returns_422",
        ])
        findings = analyze([run])
        contract = [f for f in findings if f.category == FindingCategory.API_CONTRACT]
        assert contract, "Expected an API contract finding"

    def test_state_failures_produce_functional_finding(self):
        run = self._run_with_failures([
            "TestStateTransitions::test_update_does_not_reset_completed",
        ])
        findings = analyze([run])
        functional = [f for f in findings if f.category == FindingCategory.FUNCTIONAL]
        assert functional, "Expected a functional finding"

    def test_tooling_unavailable_produces_high_finding(self):
        proj = ProjectInfo(
            language=Language.PYTHON,
            confidence=0.9,
            test_command="pytest",
            test_command_available=False,
        )
        run = TestRunResult(
            project=proj,
            command="pytest",
            exit_code=-1,
            stdout="",
            stderr="",
            duration_seconds=0.0,
            unavailable_reason="'pytest' not found on PATH",
        )
        findings = analyze([run])
        tooling = [f for f in findings if f.category == FindingCategory.TOOLING]
        assert tooling
        assert tooling[0].severity == Severity.HIGH

    def test_all_passed_no_findings(self):
        proj = ProjectInfo(language=Language.PYTHON, confidence=0.9)
        run = TestRunResult(
            project=proj,
            command="pytest -v",
            exit_code=0,
            stdout="",
            stderr="",
            duration_seconds=1.0,
            total=69,
            passed=69,
            failed=0,
            failures=[],
        )
        findings = analyze([run])
        # No failures → at most INFO findings (none expected with zero failures)
        blockers = [f for f in findings if f.severity == Severity.BLOCKER]
        assert not blockers

    def test_generic_failures_produce_functional_blocker(self):
        run = self._run_with_failures([
            "TestFoo::test_something_generic",
        ])
        findings = analyze([run])
        functional = [f for f in findings if f.category == FindingCategory.FUNCTIONAL]
        assert functional
        assert any(f.severity == Severity.BLOCKER for f in functional)


# ===========================================================================
# 5.  Release decision policy
# ===========================================================================

class TestReleaseDecisionPolicy:
    """Test the release decision policy."""

    def _finding(self, severity: Severity, category=FindingCategory.FUNCTIONAL):
        from releaseguard.models.core import Finding
        return Finding(
            category=category,
            severity=severity,
            title="test",
            summary="test",
            evidence="test",
        )

    def test_no_findings_is_ready(self):
        assert decide([]) == ReleaseDecision.READY

    def test_info_only_is_ready(self):
        assert decide([self._finding(Severity.INFO)]) == ReleaseDecision.READY

    def test_low_only_is_ready(self):
        assert decide([self._finding(Severity.LOW)]) == ReleaseDecision.READY

    def test_medium_only_is_ready(self):
        # Medium does not trigger REVIEW in the default policy
        assert decide([self._finding(Severity.MEDIUM)]) == ReleaseDecision.READY

    def test_high_is_review_required(self):
        assert decide([self._finding(Severity.HIGH)]) == ReleaseDecision.REVIEW_REQUIRED

    def test_blocker_is_blocked(self):
        assert decide([self._finding(Severity.BLOCKER)]) == ReleaseDecision.BLOCKED

    def test_blocker_overrides_high(self):
        findings = [
            self._finding(Severity.HIGH),
            self._finding(Severity.BLOCKER),
        ]
        assert decide(findings) == ReleaseDecision.BLOCKED

    def test_multiple_highs_still_review_required(self):
        findings = [self._finding(Severity.HIGH)] * 3
        assert decide(findings) == ReleaseDecision.REVIEW_REQUIRED
