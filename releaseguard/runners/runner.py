"""Safe test execution for ReleaseGuard."""

from __future__ import annotations

import shlex
import subprocess
import time
from pathlib import Path

from releaseguard.models.core import ProjectInfo, TestRunResult


# How long to wait for any test command before giving up (seconds)
_DEFAULT_TIMEOUT = 300


def run_tests(project: ProjectInfo, repo_path: Path) -> TestRunResult:
    """Execute the test command for *project* inside *repo_path*.

    Always returns a TestRunResult — never raises.  If the tool is not
    available or the command cannot be executed, the result carries an
    explanatory ``unavailable_reason``.
    """
    if project.test_command is None:
        return _unavailable(project, "no test command detected")

    if project.test_command_available is False:
        executable = project.test_command.split()[0]
        # On some systems (Windows), the executable may not be on PATH but
        # still runnable as a Python module (e.g. python -m pytest).
        # Attempt a module-based fallback before giving up.
        module_fallback_parts = _module_fallback_parts(project.test_command)
        if module_fallback_parts is None:
            return _unavailable(
                project,
                f"'{executable}' not found on PATH - install it to run tests",
            )
        cmd_parts = module_fallback_parts
    else:
        cmd_parts = shlex.split(project.test_command)

    # For pytest, run from the sub-directory that contains the project files
    # For other tools, run from repo_path root.
    cwd = _resolve_cwd(project, repo_path)

    # Add useful flags (e.g. -v for pytest)
    cmd_parts = _augment_command(cmd_parts)

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
            command=" ".join(cmd_parts),
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            duration_seconds=duration,
        )
    except FileNotFoundError:
        return _unavailable(
            project, f"executable not found: {cmd_parts[0]}"
        )
    except subprocess.TimeoutExpired:
        return _unavailable(
            project, f"test command timed out after {_DEFAULT_TIMEOUT}s"
        )
    except Exception as exc:  # noqa: BLE001
        return _unavailable(project, f"unexpected error: {exc}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unavailable(project: ProjectInfo, reason: str) -> TestRunResult:
    return TestRunResult(
        project=project,
        command=project.test_command or "",
        exit_code=-1,
        stdout="",
        stderr="",
        duration_seconds=0.0,
        unavailable_reason=reason,
    )


def _resolve_cwd(project: ProjectInfo, repo_path: Path) -> Path:
    """Determine the working directory to run tests from.

    Tries to find the sub-directory that is the root of the detected project
    (i.e. the directory containing the definitive project file).
    Falls back to repo_path if no sub-project root is found.
    """
    from releaseguard.models.core import Language

    # For each language, pick the primary marker file that indicates project root
    _ROOT_MARKERS: dict[Language, list[str]] = {
        Language.PYTHON: ["requirements.txt", "pyproject.toml", "setup.py", "setup.cfg"],
        Language.RUST: ["Cargo.toml"],
        Language.GO: ["go.mod"],
        Language.NODE: ["package.json"],
        Language.JAVA: ["pom.xml", "build.gradle", "build.gradle.kts"],
    }

    markers = _ROOT_MARKERS.get(project.language, [])
    if not markers:
        return repo_path

    # Find the directory containing any marker that was in our evidence files
    for evidence in project.evidence_files:
        for marker in markers:
            if evidence.endswith(marker) or Path(evidence).name == marker:
                candidate = (repo_path / evidence).parent
                if candidate.is_dir():
                    return candidate

    # Fallback: find any marker anywhere under repo_path
    for marker in markers:
        candidates = list(repo_path.rglob(marker))
        if candidates:
            return candidates[0].parent

    return repo_path


def _augment_command(cmd_parts: list[str]) -> list[str]:
    """Add useful flags to well-known test commands."""
    # Detect pytest invocation: either 'pytest' or 'python -m pytest'
    is_pytest = (
        cmd_parts[0] == "pytest"
        or (len(cmd_parts) >= 3 and cmd_parts[1] == "-m" and cmd_parts[2] == "pytest")
    )
    if is_pytest:
        # -v for verbose output, helps parse individual test names
        if "-v" not in cmd_parts:
            cmd_parts = [*cmd_parts, "-v"]
    return cmd_parts


def _module_fallback_parts(command: str) -> list[str] | None:
    """Return a cmd_parts list using 'python -m <module>' if applicable.

    On Windows the tool executable may not be on PATH even when the Python
    package is installed. Returns None if no fallback is known.
    Using sys.executable directly avoids shlex splitting a path with spaces.
    """
    import sys
    _FALLBACKS: dict[str, str] = {
        "pytest": "pytest",
    }
    tool = command.split()[0]
    module = _FALLBACKS.get(tool)
    if module is None:
        return None
    return [sys.executable, "-m", module]
