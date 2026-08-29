"""Test command detection for each supported language."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from releaseguard.models.core import Language, ProjectInfo


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_test_command(project: ProjectInfo, repo_path: Path) -> ProjectInfo:
    """Populate the project's test command and tool availability."""

    project_root = _resolve_project_root(project, repo_path)

    command, available = _pick_command(
        language=project.language,
        project_root=project_root,
    )

    project.test_command = command
    project.test_command_available = available

    return project


# ---------------------------------------------------------------------------
# Command selection
# ---------------------------------------------------------------------------


def _pick_command(
    language: Language,
    project_root: Path,
) -> tuple[str | None, bool | None]:
    """Return the test command and whether required tooling is available."""

    # Python is handled specially by the runner using sys.executable.
    if language == Language.PYTHON:
        return "python -m pytest -q", True

    # Rust
    if language == Language.RUST:
        cargo = _resolve_executable("cargo")

        if cargo:
            return f"{cargo} test", True

        return "cargo test", False

    # Go
    #
    # Use JSON output so ReleaseGuard can reliably determine the number
    # of tests that passed, failed, or were skipped.
    if language == Language.GO:
        go = _resolve_executable("go")

        if go:
            return f"{go} test -json ./...", True

        return "go test -json ./...", False

    # Node.js
    if language == Language.NODE:
        return _resolve_node_command(project_root)

    # Java
    if language == Language.JAVA:
        return _resolve_java_command(project_root)

    return None, None


# ---------------------------------------------------------------------------
# Project root resolution
# ---------------------------------------------------------------------------


def _resolve_project_root(
    project: ProjectInfo,
    repo_path: Path,
) -> Path:
    """Resolve the actual directory containing the detected project."""

    if project.project_path:
        candidate = repo_path / project.project_path

        if candidate.is_dir():
            return candidate

    for evidence_file in project.evidence_files:
        evidence_path = repo_path / evidence_file

        if evidence_path.exists():
            return evidence_path.parent

    return repo_path


# ---------------------------------------------------------------------------
# Executable resolution
# ---------------------------------------------------------------------------


def _resolve_executable(name: str) -> str | None:
    """Return a runnable executable name if available on PATH."""

    candidates = [name]

    if os.name == "nt":
        candidates.extend(
            [
                f"{name}.cmd",
                f"{name}.bat",
                f"{name}.exe",
            ]
        )

    for candidate in candidates:
        if shutil.which(candidate):
            return candidate

    return None


# ---------------------------------------------------------------------------
# Node.js
# ---------------------------------------------------------------------------


def _resolve_node_command(
    project_root: Path,
) -> tuple[str, bool]:
    """Resolve the correct Node.js test command."""

    npm = _resolve_executable("npm")

    if npm:
        return f"{npm} test", True

    return "npm test", False


# ---------------------------------------------------------------------------
# Java
# ---------------------------------------------------------------------------


def _resolve_java_command(
    project_root: Path,
) -> tuple[str | None, bool | None]:
    """Resolve Maven or Gradle test commands for a Java project."""

    pom_file = project_root / "pom.xml"

    gradle_file = project_root / "build.gradle"
    gradle_kts_file = project_root / "build.gradle.kts"

    if pom_file.is_file():
        return _resolve_maven(project_root)

    if gradle_file.is_file() or gradle_kts_file.is_file():
        return _resolve_gradle(project_root)

    return None, None


# ---------------------------------------------------------------------------
# Wrapper resolution
# ---------------------------------------------------------------------------


def _local_wrappers(repo_path: Path, base: str) -> list[str]:
    """Find project-local Maven or Gradle wrapper files.

    This function is retained for backward compatibility with the test suite.

    Examples on Windows:
        mvnw.cmd
        mvnw.bat
        gradlew.cmd
        gradlew.bat

    Examples on Unix:
        mvnw
        gradlew
    """

    candidates = [base]

    if os.name == "nt":
        candidates.extend(
            [
                f"{base}.cmd",
                f"{base}.bat",
            ]
        )

    wrappers: list[str] = []

    for candidate in candidates:
        path = repo_path / candidate

        if path.is_file():
            wrappers.append(str(path))
            break

    return wrappers


def _find_wrapper(
    project_root: Path,
    base_name: str,
) -> Path | None:
    """Find a Maven or Gradle wrapper in the project root."""

    wrappers = _local_wrappers(project_root, base_name)

    if not wrappers:
        return None

    return Path(wrappers[0])


def _wrapper_command(
    wrapper: Path,
    argument: str,
) -> str:
    """Build a safely quoted wrapper command."""

    return f'"{wrapper}" {argument}'


# ---------------------------------------------------------------------------
# Maven
# ---------------------------------------------------------------------------


def _resolve_maven(
    project_root: Path,
) -> tuple[str, bool]:
    """Resolve the best available Maven test command."""

    wrapper = _find_wrapper(project_root, "mvnw")

    if wrapper is not None:
        return _wrapper_command(wrapper, "test"), True

    mvn = _resolve_executable("mvn")

    if mvn:
        return f"{mvn} test", True

    return "mvn test", False


# ---------------------------------------------------------------------------
# Gradle
# ---------------------------------------------------------------------------


def _resolve_gradle(
    project_root: Path,
) -> tuple[str, bool]:
    """Resolve the best available Gradle test command."""

    wrapper = _find_wrapper(project_root, "gradlew")

    if wrapper is not None:
        return _wrapper_command(wrapper, "test"), True

    gradle = _resolve_executable("gradle")

    if gradle:
        return f"{gradle} test", True

    return "gradle test", False


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


def _check_tool(
    command: str,
    executable: str,
) -> tuple[str, bool]:
    """Backward-compatible executable availability helper."""

    available = _resolve_executable(executable) is not None

    return command, available