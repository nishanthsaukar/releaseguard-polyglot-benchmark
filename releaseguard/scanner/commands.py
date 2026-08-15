"""Test command detection for each language."""

from __future__ import annotations

import shutil
from pathlib import Path

from releaseguard.models.core import Language, ProjectInfo


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_test_command(project: ProjectInfo, repo_path: Path) -> ProjectInfo:
    """Populate project.test_command and project.test_command_available.

    Modifies the ProjectInfo in-place and also returns it for convenience.
    """
    command, available = _pick_command(project.language, repo_path)
    project.test_command = command
    project.test_command_available = available
    return project


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _pick_command(language: Language, repo_path: Path) -> tuple[str | None, bool | None]:
    """Return (command_string, is_available).

    Returns (None, None) when no test command is applicable.
    Returns (cmd, False) when the tool is not installed.
    Returns (cmd, True) when the tool is installed and a project file exists.
    """
    if language == Language.PYTHON:
        return _check_tool("pytest", "pytest")

    if language == Language.RUST:
        return _check_tool("cargo test", "cargo")

    if language == Language.GO:
        return _check_tool("go test ./...", "go")

    if language == Language.NODE:
        # Require package.json with a test script
        pkg = repo_path / "package.json"
        # Look one level deeper too (monorepo)
        if not pkg.exists():
            candidates = list(repo_path.rglob("package.json"))
            pkg = candidates[0] if candidates else pkg
        return _check_tool("npm test", "npm")

    if language == Language.JAVA:
        # Prefer Maven if pom.xml exists, fall back to Gradle
        has_pom = bool(list(repo_path.rglob("pom.xml")))
        has_gradle = bool(
            list(repo_path.rglob("build.gradle"))
            + list(repo_path.rglob("build.gradle.kts"))
        )
        if has_pom:
            return _check_tool("mvn test", "mvn")
        if has_gradle:
            return _check_tool("gradle test", "gradle")
        return None, None

    return None, None


def _check_tool(command: str, executable: str) -> tuple[str, bool]:
    """Return (command, True) if executable is on PATH, else (command, False)."""
    available = shutil.which(executable) is not None
    return command, available
