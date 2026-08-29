"""Comprehensive tests for ReleaseGuard polyglot test infrastructure.

Covers all requirements from the multi-language extension spec:

- Project detection (per-root, per-language, nested)
- Working directory resolution (correct cwd per language)
- Node.js: package.json test script check
- Node.js parser: Jest, Mocha, unknown output
- Java parser: Maven Surefire, Gradle
- Rust parser: cargo test output
- Python parser: pytest (regression)
- Zero / unknown test safety rules
- Release decision safety
- Multi-project isolation
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from releaseguard.models.core import (
    Finding,
    FindingCategory,
    Language,
    ProjectInfo,
    ReleaseDecision,
    Severity,
    TestFailure,
    TestRunResult,
)
from releaseguard.analyzer.rules import analyze
from releaseguard.parsers.java_parser import parse_java
from releaseguard.parsers.node_parser import parse_node
from releaseguard.parsers.pytest_parser import parse_pytest
from releaseguard.parsers.rust_parser import parse_rust
from releaseguard.policy.policy import decide
from releaseguard.scanner.detector import detect_projects
from releaseguard.runners.runner import _resolve_cwd, _check_node_test_script


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _proj(
    lang: Language,
    evidence: list[str] | None = None,
    project_path: str = ".",
) -> ProjectInfo:
    return ProjectInfo(
        language=lang,
        confidence=0.9,
        evidence_files=evidence or [],
        project_path=project_path,
        test_command="test",
    )


def _run(
    lang: Language,
    stdout: str = "",
    stderr: str = "",
    exit_code: int = 0,
    total: int | None = None,
    passed: int | None = None,
    failed: int | None = None,
    skipped: int | None = None,
    execution_error: str | None = None,
    unavailable_reason: str | None = None,
) -> TestRunResult:
    return TestRunResult(
        project=_proj(lang),
        command="test",
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_seconds=0.1,
        total=total,
        passed=passed,
        failed=failed,
        skipped=skipped,
        execution_error=execution_error,
        unavailable_reason=unavailable_reason,
    )


def _make_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    """Create a temp repo with given relative-path -> content mapping."""
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return tmp_path


# ===========================================================================
# 1. PROJECT DETECTION
# ===========================================================================

class TestProjectDetection:

    def test_detects_python_project(self, tmp_path):
        _make_repo(tmp_path, {"pyproject.toml": "[tool.pytest]"})
        projects = detect_projects(tmp_path)
        assert any(p.language == Language.PYTHON for p in projects)

    def test_detects_python_from_requirements(self, tmp_path):
        _make_repo(tmp_path, {"requirements.txt": "pytest"})
        projects = detect_projects(tmp_path)
        assert any(p.language == Language.PYTHON for p in projects)

    def test_detects_node_project(self, tmp_path):
        _make_repo(tmp_path, {"package.json": '{"name":"app"}'})
        projects = detect_projects(tmp_path)
        assert any(p.language == Language.NODE for p in projects)

    def test_detects_maven_project(self, tmp_path):
        _make_repo(tmp_path, {"pom.xml": "<project/>"})
        projects = detect_projects(tmp_path)
        assert any(p.language == Language.JAVA for p in projects)

    def test_detects_gradle_project(self, tmp_path):
        _make_repo(tmp_path, {"build.gradle": "// gradle"})
        projects = detect_projects(tmp_path)
        assert any(p.language == Language.JAVA for p in projects)

    def test_detects_rust_project(self, tmp_path):
        _make_repo(tmp_path, {"Cargo.toml": "[package]"})
        projects = detect_projects(tmp_path)
        assert any(p.language == Language.RUST for p in projects)

    def test_detects_nested_node_project(self, tmp_path):
        """Node project inside a subdirectory should be detected."""
        _make_repo(tmp_path, {
            "backend/package.json": '{"name":"backend","scripts":{"test":"jest"}}',
        })
        projects = detect_projects(tmp_path)
        node_projects = [p for p in projects if p.language == Language.NODE]
        assert len(node_projects) >= 1
        # Evidence or project_path should reference the backend subdirectory
        p = node_projects[0]
        assert "backend" in p.project_path or any("backend" in e for e in p.evidence_files)

    def test_detects_two_node_projects_independently(self, tmp_path):
        """Two separate Node projects in sub-directories both detected."""
        _make_repo(tmp_path, {
            "frontend/package.json": '{"name":"frontend","scripts":{"test":"jest"}}',
            "backend/package.json": '{"name":"backend","scripts":{"test":"mocha"}}',
        })
        projects = detect_projects(tmp_path)
        node_projects = [p for p in projects if p.language == Language.NODE]
        assert len(node_projects) == 2

    def test_detects_polyglot_monorepo(self, tmp_path):
        """All four supported languages detected in one repo."""
        _make_repo(tmp_path, {
            "python-service/pyproject.toml": "[tool.pytest]",
            "node-service/package.json": '{"name":"node","scripts":{"test":"jest"}}',
            "java-service/pom.xml": "<project/>",
            "rust-service/Cargo.toml": "[package]",
        })
        projects = detect_projects(tmp_path)
        langs = {p.language for p in projects}
        assert Language.PYTHON in langs
        assert Language.NODE in langs
        assert Language.JAVA in langs
        assert Language.RUST in langs

    def test_node_modules_not_detected_as_project(self, tmp_path):
        """package.json inside node_modules must not create a project."""
        _make_repo(tmp_path, {
            "python-service/requirements.txt": "pytest",
            "python-service/node_modules/lodash/package.json": '{"name":"lodash"}',
        })
        projects = detect_projects(tmp_path)
        langs = {p.language for p in projects}
        assert Language.NODE not in langs
        assert Language.PYTHON in langs

    def test_evidence_files_contain_marker(self, tmp_path):
        """Each detected project's evidence_files includes the marker file."""
        _make_repo(tmp_path, {"Cargo.toml": "[package]"})
        projects = detect_projects(tmp_path)
        rust = next(p for p in projects if p.language == Language.RUST)
        assert any("Cargo.toml" in e for e in rust.evidence_files)


# ===========================================================================
# 2. WORKING DIRECTORY
# ===========================================================================

class TestWorkingDirectory:

    def test_python_cwd_is_pyproject_parent(self, tmp_path):
        _make_repo(tmp_path, {"service/pyproject.toml": "[tool.pytest]"})
        proj = _proj(Language.PYTHON, ["service/pyproject.toml"], "service")
        cwd = _resolve_cwd(proj, tmp_path)
        assert cwd == tmp_path / "service"

    def test_python_cwd_is_requirements_parent(self, tmp_path):
        _make_repo(tmp_path, {"app/requirements.txt": "pytest"})
        proj = _proj(Language.PYTHON, ["app/requirements.txt"], "app")
        cwd = _resolve_cwd(proj, tmp_path)
        assert cwd == tmp_path / "app"

    def test_node_cwd_is_package_json_parent(self, tmp_path):
        _make_repo(tmp_path, {"backend/package.json": "{}"})
        proj = _proj(Language.NODE, ["backend/package.json"], "backend")
        cwd = _resolve_cwd(proj, tmp_path)
        assert cwd == tmp_path / "backend"

    def test_node_cwd_nested_project(self, tmp_path):
        """Nested Node project uses correct subdirectory."""
        _make_repo(tmp_path, {
            "services/frontend/package.json": '{"name":"frontend"}',
        })
        proj = _proj(
            Language.NODE,
            ["services/frontend/package.json"],
            "services/frontend",
        )
        cwd = _resolve_cwd(proj, tmp_path)
        assert cwd == tmp_path / "services" / "frontend"

    def test_java_maven_cwd_is_pom_parent(self, tmp_path):
        _make_repo(tmp_path, {"java-service/pom.xml": "<project/>"})
        proj = _proj(Language.JAVA, ["java-service/pom.xml"], "java-service")
        cwd = _resolve_cwd(proj, tmp_path)
        assert cwd == tmp_path / "java-service"

    def test_java_gradle_cwd_is_build_gradle_parent(self, tmp_path):
        _make_repo(tmp_path, {"java-service/build.gradle": "// gradle"})
        proj = _proj(Language.JAVA, ["java-service/build.gradle"], "java-service")
        cwd = _resolve_cwd(proj, tmp_path)
        assert cwd == tmp_path / "java-service"

    def test_rust_cwd_is_cargo_toml_parent(self, tmp_path):
        _make_repo(tmp_path, {"rust-service/Cargo.toml": "[package]"})
        proj = _proj(Language.RUST, ["rust-service/Cargo.toml"], "rust-service")
        cwd = _resolve_cwd(proj, tmp_path)
        assert cwd == tmp_path / "rust-service"

    def test_falls_back_to_repo_root(self, tmp_path):
        proj = _proj(Language.PYTHON, [], ".")
        cwd = _resolve_cwd(proj, tmp_path)
        assert cwd == tmp_path


# ===========================================================================
# 3. NODE.JS TEST SCRIPT CHECK
# ===========================================================================

class TestNodeTestScriptCheck:

    def test_returns_none_when_test_script_present(self, tmp_path):
        pkg = tmp_path / "package.json"
        pkg.write_text(json.dumps({"scripts": {"test": "jest"}}))
        assert _check_node_test_script(tmp_path) is None

    def test_returns_reason_when_no_scripts_key(self, tmp_path):
        pkg = tmp_path / "package.json"
        pkg.write_text(json.dumps({"name": "app"}))
        reason = _check_node_test_script(tmp_path)
        assert reason is not None
        assert "test" in reason.lower()

    def test_returns_reason_when_test_not_in_scripts(self, tmp_path):
        pkg = tmp_path / "package.json"
        pkg.write_text(json.dumps({"scripts": {"build": "webpack"}}))
        reason = _check_node_test_script(tmp_path)
        assert reason is not None

    def test_returns_reason_for_npm_placeholder_script(self, tmp_path):
        pkg = tmp_path / "package.json"
        pkg.write_text(json.dumps({
            "scripts": {"test": 'echo "Error: no test specified" && exit 1'}
        }))
        reason = _check_node_test_script(tmp_path)
        assert reason is not None

    def test_returns_none_when_no_package_json(self, tmp_path):
        """No package.json -> return None (let npm fail naturally)."""
        assert _check_node_test_script(tmp_path) is None

    def test_returns_none_when_package_json_invalid_json(self, tmp_path):
        pkg = tmp_path / "package.json"
        pkg.write_text("{bad json here}")
        assert _check_node_test_script(tmp_path) is None

    def test_no_test_script_creates_tooling_finding_via_analyzer(self):
        """Missing test script -> unavailable run -> HIGH tooling finding."""
        result = TestRunResult(
            project=_proj(Language.NODE, ["package.json"]),
            command="npm test",
            exit_code=-1,
            stdout="",
            stderr="",
            duration_seconds=0.0,
            unavailable_reason=(
                "package.json has no 'scripts.test' command — "
                "no test suite is configured for this Node.js project"
            ),
        )
        findings = analyze([result])
        tooling = [f for f in findings if f.category == FindingCategory.TOOLING]
        assert tooling
        assert tooling[0].severity == Severity.HIGH


# ===========================================================================
# 4. NODE.JS PARSER
# ===========================================================================

class TestNodeParserExtended:

    def _parse(self, stdout="", stderr="", exit_code=0) -> TestRunResult:
        r = _run(Language.NODE, stdout=stdout, stderr=stderr, exit_code=exit_code)
        return parse_node(r)

    def test_jest_all_passing(self):
        stdout = "Tests:       5 passed, 5 total\n"
        r = self._parse(stdout=stdout)
        assert r.total == 5
        assert r.passed == 5
        assert r.failed == 0

    def test_jest_with_failures(self):
        stdout = "Tests:       2 failed, 3 passed, 5 total\n"
        r = self._parse(stdout=stdout, exit_code=1)
        assert r.total == 5
        assert r.passed == 3
        assert r.failed == 2

    def test_mocha_passing(self):
        stdout = "  5 passing (42ms)\n"
        r = self._parse(stdout=stdout)
        assert r.passed == 5
        assert r.failed == 0

    def test_mocha_failures(self):
        stdout = "  3 passing (1s)\n  2 failing\n"
        r = self._parse(stdout=stdout, exit_code=1)
        assert r.passed == 3
        assert r.failed == 2

    def test_unknown_npm_output_leaves_counts_none(self):
        """npm output with no recognisable format -> total remains None."""
        r = self._parse(stdout="Done in 1.2s\n")
        assert r.total is None

    def test_npm_failure_exit_nonzero_unknown_counts(self):
        """npm fails but output is unrecognisable -> total still None."""
        r = self._parse(stdout="Error: Command failed\n", exit_code=1)
        assert r.total is None

    def test_jest_suite_summary_parsed(self):
        """Jest 'Tests:' line with multiple counts."""
        stdout = textwrap.dedent("""\
            Test Suites: 2 passed, 2 total
            Tests:       10 passed, 10 total
            Time:        1.5s
        """)
        r = self._parse(stdout=stdout)
        assert r.total == 10
        assert r.passed == 10


# ===========================================================================
# 5. JAVA PARSER
# ===========================================================================

class TestJavaParserExtended:

    def _parse(self, stdout="", stderr="", exit_code=0) -> TestRunResult:
        r = _run(Language.JAVA, stdout=stdout, stderr=stderr, exit_code=exit_code)
        return parse_java(r)

    def test_maven_all_passing(self):
        stdout = "Tests run: 10, Failures: 0, Errors: 0, Skipped: 0 - in com.example.MyTest\n"
        r = self._parse(stdout=stdout)
        assert r.total == 10
        assert r.passed == 10
        assert r.failed == 0
        assert r.skipped == 0

    def test_maven_with_failures(self):
        stdout = "Tests run: 5, Failures: 2, Errors: 0, Skipped: 0 - in com.example.MyTest\n"
        r = self._parse(stdout=stdout, exit_code=1)
        assert r.total == 5
        assert r.failed == 2
        assert r.passed == 3

    def test_maven_does_not_double_count_summary_line(self):
        """The aggregate [INFO] Results: line must not be counted."""
        stdout = textwrap.dedent("""\
            Tests run: 10, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.1 s - in com.example.MyTest
            [INFO] Results:
            [INFO] Tests run: 10, Failures: 0, Errors: 0, Skipped: 0
        """)
        r = self._parse(stdout=stdout)
        assert r.total == 10

    def test_gradle_all_passing(self):
        stdout = "10 tests completed\n"
        r = self._parse(stdout=stdout)
        assert r.total == 10
        assert r.passed == 10
        assert r.failed == 0

    def test_gradle_with_failures(self):
        stdout = "10 tests completed, 2 failed\n"
        r = self._parse(stdout=stdout, exit_code=1)
        assert r.total == 10
        assert r.failed == 2
        assert r.passed == 8

    def test_gradle_with_skipped(self):
        stdout = "10 tests completed, 1 failed, 2 skipped\n"
        r = self._parse(stdout=stdout, exit_code=1)
        assert r.total == 10
        assert r.failed == 1
        assert r.skipped == 2
        assert r.passed == 7

    def test_unknown_output_leaves_counts_none(self):
        r = self._parse(stdout="BUILD SUCCESS\n")
        assert r.total is None
        assert r.passed is None


# ===========================================================================
# 6. RUST PARSER
# ===========================================================================

class TestRustParserExtended:

    def _parse(self, stdout="", stderr="", exit_code=0) -> TestRunResult:
        r = _run(Language.RUST, stdout=stdout, stderr=stderr, exit_code=exit_code)
        return parse_rust(r)

    def test_cargo_all_passing(self):
        stdout = "test result: ok. 10 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out\n"
        r = self._parse(stdout=stdout)
        assert r.total == 10
        assert r.passed == 10
        assert r.failed == 0
        assert r.skipped == 0

    def test_cargo_with_failures(self):
        stdout = "test result: FAILED. 8 passed; 2 failed; 0 ignored; 0 measured; 0 filtered out\n"
        r = self._parse(stdout=stdout, exit_code=1)
        assert r.total == 10
        assert r.passed == 8
        assert r.failed == 2

    def test_cargo_with_ignored(self):
        stdout = "test result: ok. 7 passed; 0 failed; 3 ignored; 0 measured; 0 filtered out\n"
        r = self._parse(stdout=stdout)
        assert r.total == 10
        assert r.passed == 7
        assert r.skipped == 3

    def test_cargo_no_output_leaves_counts_none(self):
        r = self._parse(stdout="")
        assert r.total is None

    def test_cargo_compile_error_sets_execution_error(self):
        stdout = "error[E0425]: cannot find value `foo`\n"
        r = self._parse(stdout=stdout, exit_code=101)
        assert r.execution_error is not None


# ===========================================================================
# 7. PYTHON PARSER — regression
# ===========================================================================

class TestPythonParserRegression:

    def _parse(self, stdout="", stderr="", exit_code=0) -> TestRunResult:
        r = _run(Language.PYTHON, stdout=stdout, stderr=stderr, exit_code=exit_code)
        return parse_pytest(r)

    def test_all_passed_counted(self):
        stdout = "========================= 69 passed in 0.98s =========================\n"
        r = self._parse(stdout=stdout)
        assert r.passed == 69
        assert r.failed == 0
        assert r.total == 69

    def test_failed_and_passed_counted(self):
        stdout = "========================= 11 failed, 58 passed in 1.23s =========================\n"
        r = self._parse(stdout=stdout, exit_code=1)
        assert r.failed == 11
        assert r.passed == 58
        assert r.total == 69

    def test_skipped_counted(self):
        stdout = "========================= 10 passed, 2 skipped in 0.5s =========================\n"
        r = self._parse(stdout=stdout)
        assert r.skipped == 2
        assert r.total == 12

    def test_collection_error_not_counted_as_test_failure(self):
        stdout = "========================= 1 error in 0.12s =========================\n"
        r = self._parse(stdout=stdout, exit_code=2)
        assert r.failed == 0
        assert r.execution_error is not None

    def test_empty_output_does_not_crash(self):
        r = self._parse(stdout="")
        assert r.total is None or r.total == 0


# ===========================================================================
# 8. ZERO / UNKNOWN TEST SAFETY
# ===========================================================================

class TestZeroAndUnknownTestSafety:

    def test_total_zero_creates_high_finding(self):
        result = _run(Language.PYTHON, exit_code=0, total=0, passed=0, failed=0)
        findings = analyze([result])
        testing = [f for f in findings if f.category == FindingCategory.TESTING]
        assert any(f.severity == Severity.HIGH for f in testing)

    def test_total_zero_does_not_produce_release_ready(self):
        result = _run(Language.PYTHON, exit_code=0, total=0, passed=0, failed=0)
        findings = analyze([result])
        assert decide(findings) != ReleaseDecision.READY

    def test_total_none_with_exit_zero_creates_high_finding(self):
        """Command succeeded (exit 0) but total unknown -> HIGH finding."""
        result = _run(Language.NODE, exit_code=0, total=None)
        findings = analyze([result])
        testing = [f for f in findings if f.category == FindingCategory.TESTING]
        assert any(f.severity == Severity.HIGH for f in testing), (
            f"Expected HIGH TESTING finding for total=None, got: {findings}"
        )

    def test_total_none_with_exit_zero_does_not_produce_release_ready(self):
        result = _run(Language.NODE, exit_code=0, total=None)
        findings = analyze([result])
        assert decide(findings) != ReleaseDecision.READY

    def test_total_none_with_execution_error_does_not_trigger_unverified_rule(self):
        """execution_error covers this case; unverified rule must not also fire."""
        result = _run(
            Language.RUST,
            exit_code=0,
            total=None,
            execution_error="compilation error",
        )
        findings = analyze([result])
        titles = [f.title for f in findings]
        assert any("execution error" in t.lower() for t in titles)
        unverified = [f for f in findings if "could not verify" in f.title.lower()]
        assert not unverified

    def test_total_none_with_nonzero_exit_does_not_trigger_unverified_rule(self):
        """Non-zero exit is not the unverified case."""
        result = _run(Language.JAVA, exit_code=1, total=None)
        findings = analyze([result])
        unverified = [f for f in findings if "could not verify" in f.title.lower()]
        assert not unverified

    def test_zero_tests_cannot_produce_release_ready(self):
        result = _run(Language.RUST, exit_code=0, total=0, passed=0, failed=0)
        findings = analyze([result])
        assert decide(findings) != ReleaseDecision.READY

    def test_unknown_tests_cannot_produce_release_ready(self):
        result = _run(Language.NODE, exit_code=0, total=None)
        findings = analyze([result])
        assert decide(findings) != ReleaseDecision.READY

    def test_none_is_different_from_zero(self):
        """Model distinguishes None (unknown) from 0 (empty)."""
        zero_result = _run(Language.PYTHON, exit_code=0, total=0, passed=0, failed=0)
        none_result = _run(Language.NODE, exit_code=0, total=None)
        assert zero_result.total == 0
        assert none_result.total is None
        assert zero_result.total != none_result.total


# ===========================================================================
# 9. RELEASE DECISION SAFETY
# ===========================================================================

class TestReleaseDecisionSafety:

    def _finding(self, sev: Severity, cat=FindingCategory.FUNCTIONAL) -> Finding:
        return Finding(
            category=cat,
            severity=sev,
            title="test",
            summary="test",
            evidence="test",
        )

    def test_passing_verified_tests_can_produce_ready(self):
        """Positive path: real passing tests -> no findings -> READY."""
        result = _run(Language.PYTHON, exit_code=0, total=69, passed=69, failed=0)
        findings = analyze([result])
        assert decide(findings) == ReleaseDecision.READY

    def test_failed_tests_produce_blocked(self):
        result = TestRunResult(
            project=_proj(Language.PYTHON),
            command="pytest",
            exit_code=1,
            stdout="",
            stderr="",
            duration_seconds=0.1,
            total=10,
            passed=8,
            failed=2,
            failures=[TestFailure(name="test_something"), TestFailure(name="test_other")],
        )
        findings = analyze([result])
        assert decide(findings) == ReleaseDecision.BLOCKED

    def test_zero_tests_not_ready(self):
        result = _run(Language.JAVA, exit_code=0, total=0, passed=0, failed=0)
        findings = analyze([result])
        assert decide(findings) != ReleaseDecision.READY

    def test_unknown_test_counts_not_ready(self):
        result = _run(Language.NODE, exit_code=0, total=None)
        findings = analyze([result])
        assert decide(findings) != ReleaseDecision.READY

    def test_execution_error_not_ready(self):
        result = _run(Language.RUST, execution_error="cargo build failed", exit_code=101)
        findings = analyze([result])
        assert decide(findings) != ReleaseDecision.READY

    def test_tooling_unavailable_not_ready(self):
        result = _run(Language.NODE, unavailable_reason="npm not found", exit_code=-1)
        findings = analyze([result])
        assert decide(findings) != ReleaseDecision.READY

    def test_blocker_finding_blocked(self):
        assert decide([self._finding(Severity.BLOCKER)]) == ReleaseDecision.BLOCKED

    def test_high_finding_review_required(self):
        assert decide([self._finding(Severity.HIGH)]) == ReleaseDecision.REVIEW_REQUIRED

    def test_no_findings_ready(self):
        assert decide([]) == ReleaseDecision.READY


# ===========================================================================
# 10. MULTI-PROJECT ISOLATION
# ===========================================================================

class TestMultiProjectIsolation:

    def test_one_project_failure_does_not_hide_another(self):
        """Failing Python + passing Rust -> still BLOCKED."""
        py_result = TestRunResult(
            project=_proj(Language.PYTHON),
            command="pytest",
            exit_code=1,
            stdout="",
            stderr="",
            duration_seconds=0.1,
            total=5,
            passed=3,
            failed=2,
            failures=[TestFailure(name="test_foo"), TestFailure(name="test_bar")],
        )
        rust_result = _run(Language.RUST, exit_code=0, total=10, passed=10, failed=0)
        findings = analyze([py_result, rust_result])
        assert decide(findings) == ReleaseDecision.BLOCKED

    def test_one_project_zero_tests_does_not_hide_another_pass(self):
        """One project with zero tests still blocks release."""
        passing = _run(Language.PYTHON, exit_code=0, total=10, passed=10, failed=0)
        zero = _run(Language.NODE, exit_code=0, total=0, passed=0, failed=0)
        findings = analyze([passing, zero])
        assert decide(findings) != ReleaseDecision.READY

    def test_one_unknown_project_blocks_release(self):
        """Unknown test counts in one project prevents READY."""
        passing = _run(Language.PYTHON, exit_code=0, total=10, passed=10, failed=0)
        unknown = _run(Language.JAVA, exit_code=0, total=None)
        findings = analyze([passing, unknown])
        assert decide(findings) != ReleaseDecision.READY

    def test_all_passing_multi_project_is_ready(self):
        """All projects passing with known counts -> READY."""
        py = _run(Language.PYTHON, exit_code=0, total=10, passed=10, failed=0)
        node = _run(Language.NODE, exit_code=0, total=5, passed=5, failed=0)
        rust = _run(Language.RUST, exit_code=0, total=3, passed=3, failed=0)
        java = _run(Language.JAVA, exit_code=0, total=8, passed=8, failed=0)
        findings = analyze([py, node, rust, java])
        assert decide(findings) == ReleaseDecision.READY


# ===========================================================================
# 11. JAVA RUNNER — command selection
# ===========================================================================

class TestJavaRunnerCommandSelection:

    def test_gradlew_preferred_over_system_gradle_at_project_root(self, tmp_path):
        """When gradlew exists at the project root, it is used."""
        from releaseguard.scanner.commands import detect_test_command
        java_root = tmp_path / "java-service"
        java_root.mkdir()
        (java_root / "gradlew").write_text("#!/bin/sh\nexec gradle $@")
        (java_root / "build.gradle").write_text("// gradle")
        proj = ProjectInfo(
            language=Language.JAVA,
            confidence=0.9,
            evidence_files=["java-service/build.gradle"],
            project_path="java-service",
        )
        detect_test_command(proj, tmp_path)
        assert proj.test_command is not None
        assert "gradlew" in proj.test_command

    def test_system_mvn_used_when_no_wrapper(self, tmp_path):
        from releaseguard.scanner.commands import detect_test_command
        java_root = tmp_path / "java-service"
        java_root.mkdir()
        (java_root / "pom.xml").write_text("<project/>")
        proj = ProjectInfo(
            language=Language.JAVA,
            confidence=0.9,
            evidence_files=["java-service/pom.xml"],
            project_path="java-service",
        )
        with patch("shutil.which", return_value="/usr/bin/mvn"):
            detect_test_command(proj, tmp_path)
        assert proj.test_command is not None
        assert "mvn" in proj.test_command
