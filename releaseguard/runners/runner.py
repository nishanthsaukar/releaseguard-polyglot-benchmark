from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from releaseguard.models.core import Language, ProjectInfo, TestRunResult


_DEFAULT_TIMEOUT = 300
_PYTHON_DEP_TIMEOUT = 180
_NODE_DEP_TIMEOUT = 300


# ---------------------------------------------------------------------------
# Main test runner
# ---------------------------------------------------------------------------

def run_tests(project: ProjectInfo, repo_path: Path) -> TestRunResult:
    """Execute the detected test command inside the correct project directory."""

    if project.test_command is None:
        return _unavailable(project, "no test command detected")

    # Run tests inside the actual detected project directory.
    cwd = _resolve_cwd(project, repo_path)

    # Node.js: verify that a test script exists in package.json before running.
    if project.language == Language.NODE:
        missing_reason = _check_node_test_script(cwd)
        if missing_reason:
            return _unavailable(project, missing_reason)

    # Build and augment the command.
    cmd_parts = _build_cmd_parts(project)
    cmd_parts = _augment_command(cmd_parts)

    if not cmd_parts:
        return _unavailable(project, "empty test command")

    # Resolve the executable again at execution time.
    #
    # This is important because detection may have happened in a different
    # environment, and Windows commonly exposes tools as .cmd files.
    resolved_executable = _resolve_executable(cmd_parts[0])

    if resolved_executable is None:
        return _unavailable(
            project,
            f"executable not found: {cmd_parts[0]}",
        )

    cmd_parts[0] = resolved_executable

    # Install Python dependencies when requirements.txt exists.
    if project.language == Language.PYTHON:
        _install_python_deps(cwd)

    # Install Node.js dependencies deterministically before running tests.
    if project.language == Language.NODE:
        dep_result = _install_node_deps(cwd, project)
        if dep_result is not None:
            return dep_result

    start = time.monotonic()

    try:
        proc = subprocess.run(
            cmd_parts,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=_DEFAULT_TIMEOUT,
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
            f"executable not found: {cmd_parts[0]}",
        )

    except subprocess.TimeoutExpired:
        return _unavailable(
            project,
            f"test command timed out after {_DEFAULT_TIMEOUT}s",
        )

    except Exception as exc:  # noqa: BLE001
        return _unavailable(
            project,
            f"unexpected error: {exc}",
        )


# ---------------------------------------------------------------------------
# Executable resolution
# ---------------------------------------------------------------------------

def _resolve_executable(executable: str) -> str | None:
    """
    Resolve a command to an executable available in the current environment.

    On Windows, npm and Maven are often exposed as npm.cmd and mvn.cmd.
    """

    if not executable:
        return None

    # If an absolute or relative path was supplied directly.
    executable_path = Path(executable)

    if executable_path.is_file():
        return str(executable_path)

    candidates = [executable]

    if os.name == "nt":
        lower = executable.lower()

        if not lower.endswith(".cmd"):
            candidates.append(f"{executable}.cmd")

        if not lower.endswith(".exe"):
            candidates.append(f"{executable}.exe")

        if not lower.endswith(".bat"):
            candidates.append(f"{executable}.bat")

    for candidate in candidates:
        resolved = shutil.which(candidate)

        if resolved:
            return resolved

    return None


def _display_command(cmd_parts: list[str]) -> str:
    """Create a readable command string for results."""

    return " ".join(
        f'"{part}"' if " " in part else part
        for part in cmd_parts
    )


# ---------------------------------------------------------------------------
# Command building
# ---------------------------------------------------------------------------

def _build_cmd_parts(project: ProjectInfo) -> list[str]:
    """Build subprocess arguments for the project's test command."""

    # Always use the current Python interpreter for Python projects.
    # This avoids PATH problems and ensures pytest runs with the same Python.
    if project.language == Language.PYTHON:
        return [
            sys.executable,
            "-m",
            "pytest",
        ]

    return shlex.split(project.test_command or "")


def _augment_command(cmd_parts: list[str]) -> list[str]:
    """Add useful flags to supported test commands."""

    if not cmd_parts:
        return cmd_parts

    is_pytest = (
        cmd_parts[0] == "pytest"
        or (
            len(cmd_parts) >= 3
            and cmd_parts[1] == "-m"
            and cmd_parts[2] == "pytest"
        )
    )

    if is_pytest and "-v" not in cmd_parts:
        return [*cmd_parts, "-v"]

    return cmd_parts


# ---------------------------------------------------------------------------
# Working directory
# ---------------------------------------------------------------------------

def _resolve_cwd(project: ProjectInfo, repo_path: Path) -> Path:
    """
    Return the directory containing the detected project.

    The detector stores relative paths to project evidence files, such as:

        python-app/requirements.txt
        node-app/package.json
        rust-app/Cargo.toml
        go-app/go.mod
        java-app/pom.xml

    Use the parent directory of the first valid evidence file as the
    project working directory. Fall back to project_path, then repo root.
    """

    # First preference: evidence file location.
    for evidence_file in project.evidence_files:
        evidence_path = repo_path / evidence_file

        if evidence_path.exists():
            return evidence_path.parent

    # Second preference: detected project path.
    project_root = repo_path / project.project_path

    if project_root.is_dir():
        return project_root

    # Final safety fallback.
    return repo_path


# ---------------------------------------------------------------------------
# Python dependency installation
# ---------------------------------------------------------------------------

def _install_python_deps(cwd: Path) -> None:
    """
    Install Python dependencies from requirements.txt when available.

    Failure here should not crash ReleaseGuard. Pytest will still run and
    report any missing dependency/import problems in its output.
    """

    requirements_file = cwd / "requirements.txt"

    if not requirements_file.exists():
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
                str(requirements_file),
            ],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=_PYTHON_DEP_TIMEOUT,
            check=False,
        )

    except (
        FileNotFoundError,
        subprocess.TimeoutExpired,
        OSError,
    ):
        # Do not crash the ReleaseGuard scan.
        # The actual pytest execution will provide useful failure evidence.
        return


# ---------------------------------------------------------------------------
# Node.js dependency installation
# ---------------------------------------------------------------------------

def _install_node_deps(cwd: Path, project: "ProjectInfo") -> "TestRunResult | None":
    """Install Node.js dependencies before running tests.

    Uses ``npm ci`` when package-lock.json is present (deterministic),
    otherwise falls back to ``npm install``.

    Returns None on success.
    Returns a TestRunResult with unavailable_reason set when installation fails,
    so that the caller can immediately return it without running tests.
    """
    from releaseguard.models.core import TestRunResult  # local import avoids cycle

    lock_file = cwd / "package-lock.json"
    pkg_file = cwd / "package.json"

    if lock_file.exists():
        install_cmd = ["npm", "ci"]
    elif pkg_file.exists():
        install_cmd = ["npm", "install"]
    else:
        # No package.json at all — nothing to install; let npm fail naturally.
        return None

    # Resolve the npm executable (handles Windows npm.cmd).
    npm_resolved = _resolve_executable(install_cmd[0])
    if npm_resolved is None:
        return _unavailable(
            project,
            f"npm not found on PATH; cannot install Node.js dependencies",
        )
    install_cmd[0] = npm_resolved

    try:
        proc = subprocess.run(
            install_cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=_NODE_DEP_TIMEOUT,
            check=False,
        )
    except FileNotFoundError:
        return _unavailable(project, "npm not found on PATH; cannot install Node.js dependencies")
    except subprocess.TimeoutExpired:
        return _unavailable(project, f"npm dependency installation timed out after {_NODE_DEP_TIMEOUT}s")
    except Exception as exc:  # noqa: BLE001
        return _unavailable(project, f"npm dependency installation failed with unexpected error: {exc}")

    if proc.returncode != 0:
        stderr_snippet = (proc.stderr or proc.stdout or "").strip()[:500]
        return TestRunResult(
            project=project,
            command=" ".join(install_cmd),
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            duration_seconds=0.0,
            unavailable_reason=(
                f"Node.js dependency installation failed (exit {proc.returncode}): "
                f"{stderr_snippet}"
            ),
        )

    return None


# ---------------------------------------------------------------------------
# Node.js test script check
# ---------------------------------------------------------------------------

def _check_node_test_script(cwd: Path) -> str | None:
    """Return an error reason if package.json has no usable test script.

    Returns None when a test script is present or when package.json cannot
    be read (in that case we let npm fail naturally so the error is captured).
    Returns a non-empty string when the test script is explicitly absent —
    this prevents running ``npm test`` which would exit non-zero with a
    misleading "missing script: test" message.
    """
    pkg = cwd / "package.json"

    if not pkg.exists():
        return None  # no package.json; let npm fail naturally

    try:
        data = json.loads(pkg.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return None  # unreadable; let npm fail naturally

    scripts = data.get("scripts", {})

    if not isinstance(scripts, dict):
        return "package.json scripts field is not a mapping"

    if "test" not in scripts:
        return (
            "package.json has no 'scripts.test' command — "
            "no test suite is configured for this Node.js project"
        )

    test_script = scripts["test"]
    if isinstance(test_script, str) and test_script.strip().lower() in (
        'echo "error: no test specified" && exit 1',
        "echo 'error: no test specified' && exit 1",
        'echo "error: no test specified"',
    ):
        return (
            "package.json 'scripts.test' is the npm placeholder — "
            "no real test suite is configured"
        )

    return None


# ---------------------------------------------------------------------------
# Result helpers
# ---------------------------------------------------------------------------

def _unavailable(
    project: ProjectInfo,
    reason: str,
) -> TestRunResult:
    """Create a result representing unavailable test tooling."""

    return TestRunResult(
        project=project,
        command=project.test_command or "",
        exit_code=-1,
        stdout="",
        stderr="",
        duration_seconds=0.0,
        unavailable_reason=reason,
    )