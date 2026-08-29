"""Tests for polyglot cross-platform command resolution and language runners.

Covers:
  1. Python uses sys.executable -m pytest (never standalone pytest binary)
  2. Windows Node resolution supports npm.cmd
  3. Unix/macOS Node resolution supports npm
  4. Rust uses Cargo
  5. Go uses the go executable
  6. Maven/Gradle wrappers are preferred when present
  7. Commands run from the correct project directory (cwd)
  8. Missing executables produce a clear structured finding (TOOLING HIGH)
  9. Collection/execution errors are not reported as successful scans
 10. _resolve_executable falls back to .cmd on Windows
 11. _augment_command detects sys.executable -m pytest forms
"""

from __future__ import annotations

import os
import sys
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from releaseguard.models.core import (
    FindingCategory,
    Language,
    ProjectInfo,
    Severity,
    TestRunResult,
)
from releaseguard.scanner.commands import (
    detect_test_command,
    _resolve_executable,
    _local_wrappers,
)
from releaseguard.runners.runner import _augment_command, _resolve_cwd
from releaseguard.analyzer.rules import analyze


# ===========================================================================
# Helpers
# ===========================================================================

def _project(lang: Language, evidence_files: list[str] | None = None) -> ProjectInfo:
    return ProjectInfo(
        language=lang,
        confidence=0.9,
        evidence_files=evidence_files or [],
    )


# ===========================================================================
# 1.  Python always uses sys.executable -m pytest
# ===========================================================================

class TestPythonExecutableResolution:
    """Python test command must embed sys.executable, never a bare 'pytest'."""

    def test_python_command_is_module_form(self, tmp_path):
        proj = _project(Language.PYTHON)
        detect_test_command(proj, tmp_path)
        # Human-readable display string — runner substitutes sys.executable at launch
        assert proj.test_command == "python -m pytest -q"

    def test_python_command_uses_sys_executable_at_runtime(self):
        """Runner must build cmd_parts with sys.executable, not split the string."""
        from releaseguard.runners.runner import _build_cmd_parts
        proj = _project(Language.PYTHON)
        proj.test_command = "python -m pytest -q"
        parts = _build_cmd_parts(proj)
        assert parts[0] == sys.executable
        assert parts[1:] == ["-m", "pytest"]

    def test_python_command_always_available_regardless_of_path(self, tmp_path):
        """Python is always available because we use sys.executable directly."""
        proj = _project(Language.PYTHON)
        # Even if shutil.which cannot find anything, Python must be available
        with patch("shutil.which", return_value=None):
            detect_test_command(proj, tmp_path)
        assert proj.test_command_available is True

    def test_python_command_includes_quiet_flag(self, tmp_path):
        """The -q flag is part of the display string."""
        proj = _project(Language.PYTHON)
        detect_test_command(proj, tmp_path)
        assert proj.test_command is not None
        assert "-q" in proj.test_command

    def test_augment_command_adds_verbose_to_sys_executable_form(self):
        """_augment_command recognises sys.executable -m pytest and adds -v."""
        cmd = [sys.executable, "-m", "pytest", "-q"]
        result = _augment_command(cmd)
        assert "-v" in result

    def test_augment_command_does_not_duplicate_verbose(self):
        cmd = [sys.executable, "-m", "pytest", "-v"]
        result = _augment_command(cmd)
        assert result.count("-v") == 1


# ===========================================================================
# 2 & 3.  Node.js — npm / npm.cmd resolution
# ===========================================================================

class TestNodeExecutableResolution:
    """npm must be found via npm on Unix and npm.cmd on Windows."""

    def test_node_available_when_npm_on_path(self, tmp_path):
        proj = _project(Language.NODE)
        with patch("shutil.which", side_effect=lambda name: "/usr/bin/npm" if name == "npm" else None):
            detect_test_command(proj, tmp_path)
        assert proj.test_command_available is True
        assert "npm" in (proj.test_command or "")

    def test_node_available_when_npm_cmd_on_path(self, tmp_path):
        """Windows: npm.cmd is the normal form; must be detected as available."""
        proj = _project(Language.NODE)

        def _which(name: str) -> str | None:
            return "C:\\npm\\npm.cmd" if name == "npm.cmd" else None

        with patch("os.name", "nt"):
            with patch("shutil.which", side_effect=_which):
                detect_test_command(proj, tmp_path)
        assert proj.test_command_available is True
        assert "npm.cmd" in (proj.test_command or "")

    def test_node_unavailable_when_neither_npm_nor_npm_cmd(self, tmp_path):
        proj = _project(Language.NODE)
        with patch("os.name", "nt"):
            with patch("shutil.which", return_value=None):
                detect_test_command(proj, tmp_path)
        assert proj.test_command_available is False

    def test_node_unix_does_not_use_npm_cmd(self, tmp_path):
        """On posix, npm.cmd must never appear in the command."""
        proj = _project(Language.NODE)
        with patch("os.name", "posix"):
            with patch("shutil.which", side_effect=lambda name: "/usr/bin/npm" if name == "npm" else None):
                detect_test_command(proj, tmp_path)
        assert proj.test_command is not None
        assert "npm.cmd" not in proj.test_command


# ===========================================================================
# 4.  Rust uses Cargo
# ===========================================================================

class TestRustExecutableResolution:
    """Cargo must be found correctly."""

    def test_rust_command_is_cargo_test(self, tmp_path):
        proj = _project(Language.RUST)
        detect_test_command(proj, tmp_path)
        assert proj.test_command == "cargo test"

    def test_rust_available_when_cargo_found(self, tmp_path):
        proj = _project(Language.RUST)
        with patch("shutil.which", return_value="/usr/bin/cargo"):
            detect_test_command(proj, tmp_path)
        assert proj.test_command_available is True

    def test_rust_unavailable_when_cargo_missing(self, tmp_path):
        proj = _project(Language.RUST)
        with patch("shutil.which", return_value=None):
            detect_test_command(proj, tmp_path)
        assert proj.test_command_available is False


# ===========================================================================
# 5.  Go uses the go executable
# ===========================================================================

class TestGoExecutableResolution:
    """go must be found correctly."""

    def test_go_command_is_go_test_all(self, tmp_path):
        proj = _project(Language.GO)
        detect_test_command(proj, tmp_path)
        assert proj.test_command == "go test -json ./..."

    def test_go_available_when_go_found(self, tmp_path):
        proj = _project(Language.GO)
        with patch("shutil.which", return_value="/usr/local/go/bin/go"):
            detect_test_command(proj, tmp_path)
        assert proj.test_command_available is True

    def test_go_unavailable_when_go_missing(self, tmp_path):
        proj = _project(Language.GO)
        with patch("shutil.which", return_value=None):
            detect_test_command(proj, tmp_path)
        assert proj.test_command_available is False


# ===========================================================================
# 6.  Maven / Gradle wrappers preferred over system tools
# ===========================================================================

class TestJavaWrapperPreference:
    """Project-local mvnw / gradlew must be preferred over system mvn / gradle."""

    def test_mvnw_preferred_over_system_mvn(self, tmp_path):
        (tmp_path / "pom.xml").write_text("<project/>")
        (tmp_path / "mvnw").write_text("#!/bin/sh\nexec mvn $@")
        proj = _project(Language.JAVA)
        detect_test_command(proj, tmp_path)
        assert proj.test_command is not None
        assert "mvnw" in proj.test_command
        assert proj.test_command_available is True

    def test_mvnw_cmd_preferred_on_windows(self, tmp_path):
        (tmp_path / "pom.xml").write_text("<project/>")
        (tmp_path / "mvnw.cmd").write_text("@echo off\ncall mvn %*")
        proj = _project(Language.JAVA)
        with patch("os.name", "nt"):
            detect_test_command(proj, tmp_path)
        assert proj.test_command is not None
        assert "mvnw" in proj.test_command
        assert proj.test_command_available is True

    def test_gradlew_preferred_over_system_gradle(self, tmp_path):
        (tmp_path / "build.gradle").write_text("// gradle")
        (tmp_path / "gradlew").write_text("#!/bin/sh\nexec gradle $@")
        proj = _project(Language.JAVA)
        detect_test_command(proj, tmp_path)
        assert proj.test_command is not None
        assert "gradlew" in proj.test_command
        assert proj.test_command_available is True

    def test_gradlew_bat_preferred_on_windows(self, tmp_path):
        (tmp_path / "build.gradle").write_text("// gradle")
        (tmp_path / "gradlew.bat").write_text("@echo off\ncall gradle %*")
        proj = _project(Language.JAVA)
        with patch("os.name", "nt"):
            detect_test_command(proj, tmp_path)
        assert proj.test_command is not None
        assert "gradlew" in proj.test_command
        assert proj.test_command_available is True

    def test_falls_back_to_system_mvn_when_no_wrapper(self, tmp_path):
        (tmp_path / "pom.xml").write_text("<project/>")
        proj = _project(Language.JAVA)
        with patch("shutil.which", return_value="/usr/bin/mvn"):
            detect_test_command(proj, tmp_path)
        assert proj.test_command == "mvn test"
        assert proj.test_command_available is True

    def test_maven_unavailable_when_no_wrapper_and_no_system_mvn(self, tmp_path):
        (tmp_path / "pom.xml").write_text("<project/>")
        proj = _project(Language.JAVA)
        with patch("shutil.which", return_value=None):
            detect_test_command(proj, tmp_path)
        assert proj.test_command == "mvn test"
        assert proj.test_command_available is False

    def test_mvn_cmd_resolves_on_windows(self, tmp_path):
        """mvn.cmd must be accepted as a valid Maven executable on Windows."""
        (tmp_path / "pom.xml").write_text("<project/>")
        proj = _project(Language.JAVA)

        def _which(name: str) -> str | None:
            return "C:\\mvn\\bin\\mvn.cmd" if name == "mvn.cmd" else None

        with patch("os.name", "nt"):
            with patch("shutil.which", side_effect=_which):
                detect_test_command(proj, tmp_path)
        assert proj.test_command_available is True


# ===========================================================================
# 7.  Commands run from the correct project directory
# ===========================================================================

class TestCorrectCwd:
    """_resolve_cwd must return the directory containing the project marker."""

    def test_python_cwd_is_requirements_txt_parent(self, tmp_path):
        sub = tmp_path / "python-app"
        sub.mkdir()
        (sub / "requirements.txt").write_text("fastapi")
        proj = _project(Language.PYTHON, evidence_files=["python-app/requirements.txt"])
        cwd = _resolve_cwd(proj, tmp_path)
        assert cwd == sub

    def test_node_cwd_is_package_json_parent(self, tmp_path):
        sub = tmp_path / "node-app"
        sub.mkdir()
        (sub / "package.json").write_text('{"name": "x"}')
        proj = _project(Language.NODE, evidence_files=["node-app/package.json"])
        cwd = _resolve_cwd(proj, tmp_path)
        assert cwd == sub

    def test_rust_cwd_is_cargo_toml_parent(self, tmp_path):
        sub = tmp_path / "rust-app"
        sub.mkdir()
        (sub / "Cargo.toml").write_text("[package]")
        proj = _project(Language.RUST, evidence_files=["rust-app/Cargo.toml"])
        cwd = _resolve_cwd(proj, tmp_path)
        assert cwd == sub

    def test_go_cwd_is_go_mod_parent(self, tmp_path):
        sub = tmp_path / "go-app"
        sub.mkdir()
        (sub / "go.mod").write_text("module example.com/app")
        proj = _project(Language.GO, evidence_files=["go-app/go.mod"])
        cwd = _resolve_cwd(proj, tmp_path)
        assert cwd == sub

    def test_java_cwd_is_pom_xml_parent(self, tmp_path):
        sub = tmp_path / "java-app"
        sub.mkdir()
        (sub / "pom.xml").write_text("<project/>")
        proj = _project(Language.JAVA, evidence_files=["java-app/pom.xml"])
        cwd = _resolve_cwd(proj, tmp_path)
        assert cwd == sub

    def test_falls_back_to_repo_root_when_no_marker(self, tmp_path):
        proj = _project(Language.PYTHON, evidence_files=[])
        cwd = _resolve_cwd(proj, tmp_path)
        assert cwd == tmp_path


# ===========================================================================
# 8.  Missing executable → clear TOOLING finding
# ===========================================================================

class TestMissingExecutableProducesToolingFinding:
    """When a tool is unavailable, analyze() must produce a TOOLING HIGH finding."""

    def _unavailable_run(self, lang: Language, command: str) -> TestRunResult:
        proj = ProjectInfo(
            language=lang,
            confidence=0.9,
            test_command=command,
            test_command_available=False,
        )
        return TestRunResult(
            project=proj,
            command=command,
            exit_code=-1,
            stdout="",
            stderr="",
            duration_seconds=0.0,
            unavailable_reason=f"'{command.split()[0]}' not found on PATH",
        )

    def test_missing_npm_produces_tooling_finding(self):
        run = self._unavailable_run(Language.NODE, "npm test")
        findings = analyze([run])
        tooling = [f for f in findings if f.category == FindingCategory.TOOLING]
        assert tooling, "Expected a TOOLING finding for missing npm"
        assert tooling[0].severity == Severity.HIGH

    def test_missing_cargo_produces_tooling_finding(self):
        run = self._unavailable_run(Language.RUST, "cargo test")
        findings = analyze([run])
        tooling = [f for f in findings if f.category == FindingCategory.TOOLING]
        assert tooling, "Expected a TOOLING finding for missing cargo"
        assert tooling[0].severity == Severity.HIGH

    def test_missing_go_produces_tooling_finding(self):
        run = self._unavailable_run(Language.GO, "go test ./...")
        findings = analyze([run])
        tooling = [f for f in findings if f.category == FindingCategory.TOOLING]
        assert tooling, "Expected a TOOLING finding for missing go"

    def test_missing_mvn_produces_tooling_finding(self):
        run = self._unavailable_run(Language.JAVA, "mvn test")
        findings = analyze([run])
        tooling = [f for f in findings if f.category == FindingCategory.TOOLING]
        assert tooling, "Expected a TOOLING finding for missing mvn"
        assert tooling[0].severity == Severity.HIGH

    def test_tooling_finding_includes_tool_name_in_evidence(self):
        run = self._unavailable_run(Language.RUST, "cargo test")
        findings = analyze([run])
        tooling = [f for f in findings if f.category == FindingCategory.TOOLING]
        assert tooling
        assert "cargo" in tooling[0].evidence.lower() or "cargo" in tooling[0].summary.lower()


# ===========================================================================
# 9.  Collection/execution errors must not look like successful 0-test scans
# ===========================================================================

class TestCollectionErrorNotZeroTests:
    """Errors during test collection must produce a TOOLING finding, not 0 passed."""

    def _collection_error_run(self, lang: Language, command: str) -> TestRunResult:
        proj = ProjectInfo(
            language=lang,
            confidence=0.9,
            test_command=command,
            test_command_available=True,
        )
        return TestRunResult(
            project=proj,
            command=command,
            exit_code=2,
            stdout="ERROR collecting tests/test_app.py\nE   ModuleNotFoundError: No module named 'pandas'",
            stderr="",
            duration_seconds=0.1,
            total=0,
            passed=0,
            failed=0,
            execution_error="pytest reported 1 collection/execution error(s)",
        )

    def test_collection_error_produces_tooling_not_zero_test_blocker(self):
        run = self._collection_error_run(Language.PYTHON, "python -m pytest -q")
        findings = analyze([run])
        # Must produce a TOOLING finding
        assert any(f.category == FindingCategory.TOOLING for f in findings)
        # Must NOT produce a FUNCTIONAL BLOCKER claiming zero tests failed
        assert not any(
            f.category == FindingCategory.FUNCTIONAL and f.severity == Severity.BLOCKER
            for f in findings
        )

    def test_collection_error_not_reported_as_all_passed(self):
        run = self._collection_error_run(Language.PYTHON, "python -m pytest -q")
        findings = analyze([run])
        # There must be at least one non-trivial finding
        assert findings, "Collection error must produce at least one finding"
        # Zero-test success is not an acceptable outcome
        zero_test_pass = all(
            f.category == FindingCategory.TESTING and "no tests" in f.title.lower()
            for f in findings
        ) if findings else False
        assert not zero_test_pass

    def test_non_zero_exit_without_counts_produces_high_finding(self):
        """When the runner exits non-zero but no counts can be parsed,
        report a HIGH testing finding rather than silently passing."""
        proj = ProjectInfo(
            language=Language.NODE,
            confidence=0.9,
            test_command="npm test",
            test_command_available=True,
        )
        run = TestRunResult(
            project=proj,
            command="npm test",
            exit_code=1,
            stdout="",
            stderr="Error: Cannot find module './test'",
            duration_seconds=0.3,
            total=0,
            passed=0,
            failed=1,  # has_failures=True via failed>0
            execution_error=None,
        )
        findings = analyze([run])
        # Should produce a non-trivial finding (FUNCTIONAL or TESTING, HIGH or BLOCKER)
        significant = [
            f for f in findings
            if f.severity in (Severity.HIGH, Severity.BLOCKER)
        ]
        assert significant, "Non-zero exit must produce at least one significant finding"


# ===========================================================================
# 10.  _resolve_executable Windows .cmd fallback
# ===========================================================================

class TestResolveExecutable:
    """_resolve_executable must check .cmd variant on Windows."""

    def test_returns_plain_name_when_found_directly(self):
        with patch("shutil.which", return_value="/usr/bin/cargo"):
            result = _resolve_executable("cargo")
        assert result == "cargo"

    def test_returns_none_when_not_found_on_posix(self):
        with patch("os.name", "posix"):
            with patch("shutil.which", return_value=None):
                result = _resolve_executable("cargo")
        assert result is None

    def test_returns_cmd_variant_on_windows_when_direct_missing(self):
        def _which(name: str) -> str | None:
            return "C:\\npm\\npm.cmd" if name == "npm.cmd" else None

        with patch("os.name", "nt"):
            with patch("shutil.which", side_effect=_which):
                result = _resolve_executable("npm")
        assert result == "npm.cmd"

    def test_returns_none_on_windows_when_both_missing(self):
        with patch("os.name", "nt"):
            with patch("shutil.which", return_value=None):
                result = _resolve_executable("npm")
        assert result is None

    def test_direct_hit_preferred_over_cmd_on_windows(self):
        """Even on Windows, prefer the plain executable over .cmd if both exist."""
        def _which(name: str) -> str | None:
            if name == "npm":
                return "C:\\npm\\npm.exe"
            if name == "npm.cmd":
                return "C:\\npm\\npm.cmd"
            return None

        with patch("os.name", "nt"):
            with patch("shutil.which", side_effect=_which):
                result = _resolve_executable("npm")
        assert result == "npm"  # plain form wins


# ===========================================================================
# 11.  _local_wrappers — correct detection of project-local wrappers
# ===========================================================================

class TestLocalWrappers:
    """_local_wrappers must find the right wrapper file depending on platform."""

    def test_finds_mvnw_on_posix(self, tmp_path):
        (tmp_path / "mvnw").write_text("#!/bin/sh")
        with patch("os.name", "posix"):
            wrappers = _local_wrappers(tmp_path, "mvnw")
        assert wrappers
        assert "mvnw" in wrappers[0]

    def test_finds_mvnw_cmd_on_windows(self, tmp_path):
        (tmp_path / "mvnw.cmd").write_text("@echo off")
        with patch("os.name", "nt"):
            wrappers = _local_wrappers(tmp_path, "mvnw")
        assert wrappers
        assert "mvnw.cmd" in wrappers[0]

    def test_finds_gradlew_bat_on_windows(self, tmp_path):
        (tmp_path / "gradlew.bat").write_text("@echo off")
        with patch("os.name", "nt"):
            wrappers = _local_wrappers(tmp_path, "gradlew")
        assert wrappers
        assert "gradlew.bat" in wrappers[0]

    def test_returns_empty_when_no_wrapper(self, tmp_path):
        with patch("os.name", "posix"):
            wrappers = _local_wrappers(tmp_path, "mvnw")
        assert wrappers == []
