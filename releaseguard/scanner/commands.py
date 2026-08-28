"""Test command detection for each language."""

from __future__ import annotations

import os
import shutil
import sys
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
        # Store a human-readable command string for display purposes.
        # The runner uses sys.executable directly to avoid shlex.split
        # breaking paths that contain spaces (common on Windows).
        return "python -m pytest -q", True

    if language == Language.RUST:
        exe = _resolve_executable("cargo")
        return "cargo test", exe is not None

    if language == Language.GO:
        exe = _resolve_executable("go")
        return "go test ./...", exe is not None

    if language == Language.NODE:
        exe = _resolve_executable("npm")
        # Build the command using the resolved executable name so it works
        # cross-platform (npm vs npm.cmd) while displaying cleanly.
        npm_cmd = exe if exe else "npm"
        return f"{npm_cmd} test", exe is not None

    if language == Language.JAVA:
        # Prefer project-local wrappers first, then system-wide tools.
        has_pom = bool(list(repo_path.rglob("pom.xml")))
        has_gradle = bool(
            list(repo_path.rglob("build.gradle"))
            + list(repo_path.rglob("build.gradle.kts"))
        )
        if has_pom:
            cmd, available = _resolve_maven(repo_path)
            return cmd, available
        if has_gradle:
            cmd, available = _resolve_gradle(repo_path)
            return cmd, available
        return None, None

    return None, None


def _resolve_executable(name: str) -> str | None:
    """Return the executable name/path to use for *name*, or None if unavailable.

    On Windows, also checks for ``<name>.cmd`` which is the form that npm,
    mvn, and other Node/Java tooling install under.
    """
    # Direct hit first (works on Unix and Windows when on PATH as-is)
    found = shutil.which(name)
    if found:
        return name  # return the plain name, not the full path

    # Windows-specific: try the .cmd wrapper
    if os.name == "nt":
        found = shutil.which(name + ".cmd")
        if found:
            return name + ".cmd"

    return None


def _resolve_maven(repo_path: Path) -> tuple[str, bool]:
    """Return (maven_command, available) preferring local wrappers."""
    for wrapper in _local_wrappers(repo_path, "mvnw"):
        return f"{wrapper} test", True

    exe = _resolve_executable("mvn")
    return "mvn test", exe is not None


def _resolve_gradle(repo_path: Path) -> tuple[str, bool]:
    """Return (gradle_command, available) preferring local wrappers."""
    for wrapper in _local_wrappers(repo_path, "gradlew"):
        return f"{wrapper} test", True

    exe = _resolve_executable("gradle")
    return "gradle test", exe is not None


def _local_wrappers(repo_path: Path, base: str) -> list[str]:
    """Return paths to project-local wrappers (mvnw / gradlew) if they exist.

    On Windows also checks for the .cmd/.bat form.
    Returns a list of usable wrapper path strings (empty if none found).
    """
    candidates = [base]
    if os.name == "nt":
        candidates.append(base + ".cmd")
        candidates.append(base + ".bat")

    found: list[str] = []
    for candidate in candidates:
        p = repo_path / candidate
        if p.exists():
            found.append(str(p))
            break  # first match wins
    return found


def _check_tool(command: str, executable: str) -> tuple[str, bool]:
    """Return (command, True) if executable is on PATH, else (command, False).

    Kept for backward compatibility; prefer _resolve_executable() in new code.
    """
    available = _resolve_executable(executable) is not None
    return command, available
