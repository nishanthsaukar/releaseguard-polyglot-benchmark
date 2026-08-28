from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from releaseguard.models.core import Language, ProjectInfo, TestRunResult


_DEFAULT_TIMEOUT = 300


def run_tests(project: ProjectInfo, repo_path: Path) -> TestRunResult:
    """Execute tests for a detected project.

    Always returns a TestRunResult and never raises.
    """

    if project.test_command is None:
        return _unavailable(project, "no test command detected")

    cwd = _resolve_cwd(project, repo_path)

    # Build the correct command for the current language/platform.
    cmd_parts = _build_cmd_parts(project)

    # Install Python dependencies when requirements.txt exists.
    if project.language == Language.PYTHON:
        _install_python_deps(cwd)

    cmd_parts = _augment_command(cmd_parts)

    # Check whether the executable can actually be found NOW.
    executable = cmd_parts[0]

    if not _executable_available(executable):
        return _unavailable(
            project,
            f"executable not found: {executable}",
        )

    start = time.monotonic()

    try:
        proc = subprocess.run(
            cmd_parts,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=_DEFAULT_TIMEOUT,
            shell=False,
        )

        duration = time.monotonic() - start

        return TestRunResult(
            project=project,
            command=_display_command(cmd_parts),
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            duration_seconds=duration,
        )

    except FileNotFoundError:
        return _unavailable(
            project,
            f"executable not found: {executable}",
        )

    except subprocess.TimeoutExpired:
        return _unavailable(
            project,
            f"test command timed out after {_DEFAULT_TIMEOUT}s",
        )

    except Exception as exc:
        return _unavailable(
            project,
            f"unexpected error: {exc}",
        )


# ============================================================
# COMMAND BUILDING
# ============================================================

def _build_cmd_parts(project: ProjectInfo) -> list[str]:
    """Build the correct test command for each language."""

    language = project.language

    # --------------------------------------------------------
    # PYTHON
    # --------------------------------------------------------
    if language == Language.PYTHON:
        return [
            sys.executable,
            "-m",
            "pytest",
        ]

    # --------------------------------------------------------
    # NODE.JS
    # --------------------------------------------------------
    if language == Language.NODE:
        npm = _find_windows_command("npm")

        if npm is None:
            npm = "npm"

        return [
            npm,
            "test",
        ]

    # --------------------------------------------------------
    # RUST
    # --------------------------------------------------------
    if language == Language.RUST:
        cargo = _find_windows_command("cargo")

        if cargo is None:
            cargo = "cargo"

        return [
            cargo,
            "test",
        ]

    # --------------------------------------------------------
    # GO
    # --------------------------------------------------------
    if language == Language.GO:
        go = _find_windows_command("go")

        if go is None:
            go = "go"

        return [
            go,
            "test",
            "./...",
        ]

    # --------------------------------------------------------
    # JAVA / MAVEN
    # --------------------------------------------------------
    if language == Language.JAVA:
        mvn = _find_windows_command("mvn")

        if mvn is None:
            mvn = "mvn"

        return [
            mvn,
            "test",
        ]

    # Fallback
    return shlex.split(project.test_command)


# ============================================================
# EXECUTABLE DETECTION
# ============================================================

def _find_windows_command(command: str) -> str | None:
    """Find commands such as npm.cmd on Windows."""

    # Normal lookup first
    found = shutil.which(command)

    if found:
        return found

    # Windows-specific executable extensions
    if os.name == "nt":

        for extension in [".cmd", ".exe", ".bat"]:

            found = shutil.which(command + extension)

            if found:
                return found

    return None


def _executable_available(executable: str) -> bool:
    """Check whether an executable exists."""

    executable_path = Path(executable)

    # Absolute path (like sys.executable)
    if executable_path.is_absolute():
        return executable_path.exists()

    return _find_windows_command(executable) is not None


# ============================================================
# PYTHON DEPENDENCIES
# ============================================================

def _install_python_deps(cwd: Path) -> None:
    """Install requirements.txt dependencies when present."""

    req = cwd / "requirements.txt"

    if not req.exists():
        return

    try:

        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "-q",
                "-r",
                str(req),
            ],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=180,
        )

    except Exception:
        pass


# ============================================================
# PROJECT WORKING DIRECTORY
# ============================================================

def _resolve_cwd(project: ProjectInfo, repo_path: Path) -> Path:
    """Find the actual root directory of the detected project."""

    root_markers: dict[Language, list[str]] = {

        Language.PYTHON: [
            "requirements.txt",
            "pyproject.toml",
            "setup.py",
            "setup.cfg",
        ],

        Language.NODE: [
            "package.json",
        ],

        Language.RUST: [
            "Cargo.toml",
        ],

        Language.GO: [
            "go.mod",
        ],

        Language.JAVA: [
            "pom.xml",
            "build.gradle",
            "build.gradle.kts",
        ],
    }

    markers = root_markers.get(project.language, [])

    # First use scanner evidence.
    for evidence in project.evidence_files:

        evidence_path = Path(evidence)

        if evidence_path.name in markers:

            candidate = repo_path / evidence_path.parent

            if candidate.is_dir():
                return candidate

    # Otherwise search the repository.
    for marker in markers:

        candidates = list(repo_path.rglob(marker))

        if candidates:

            return candidates[0].parent

    return repo_path


# ============================================================
# COMMAND FLAGS
# ============================================================

def _augment_command(cmd_parts: list[str]) -> list[str]:

    # pytest
    if (
        len(cmd_parts) >= 3
        and cmd_parts[1] == "-m"
        and cmd_parts[2] == "pytest"
    ):

        if "-v" not in cmd_parts:
            cmd_parts.append("-v")

    return cmd_parts


# ============================================================
# RESULT HELPERS
# ============================================================

def _unavailable(
    project: ProjectInfo,
    reason: str,
) -> TestRunResult:

    return TestRunResult(
        project=project,
        command=project.test_command or "",
        exit_code=-1,
        stdout="",
        stderr="",
        duration_seconds=0.0,
        unavailable_reason=reason,
    )


def _display_command(cmd_parts: list[str]) -> str:
    """Create a readable command string."""

    return " ".join(
        f'"{part}"' if " " in part else part
        for part in cmd_parts
    )