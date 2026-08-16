from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path


_GITHUB_REPO_RE = re.compile(
    r"^https://github\.com/"
    r"(?P<owner>[A-Za-z0-9_.-]+)/"
    r"(?P<repo>[A-Za-z0-9_.-]+)"
    r"(?:\.git)?/?$",
    re.IGNORECASE,
)


class RepositoryLoadError(RuntimeError):
    """Raised when a repository target cannot be loaded."""


def is_github_url(target: str) -> bool:
    """
    Return True when target is a supported public GitHub repository URL.

    Supported forms:
        https://github.com/owner/repo
        https://github.com/owner/repo.git
        https://github.com/owner/repo/
        https://github.com/owner/repo.git/
    """
    if not isinstance(target, str):
        return False

    return _GITHUB_REPO_RE.fullmatch(target.strip()) is not None


def normalize_github_url(target: str) -> str:
    """
    Validate and normalize a GitHub repository URL.

    The returned URL always uses the canonical .git form.
    """
    if not isinstance(target, str):
        raise RepositoryLoadError(
            "Repository target must be a string."
        )

    target = target.strip()

    match = _GITHUB_REPO_RE.fullmatch(target)

    if not match:
        raise RepositoryLoadError(
            "Only public GitHub repository URLs are supported. "
            "Expected: https://github.com/<owner>/<repo> "
            "or https://github.com/<owner>/<repo>.git"
        )

    owner = match.group("owner")
    repo = match.group("repo")

    # The regex allows both repo and repo.git.
    # Remove an existing suffix before adding the canonical one.
    if repo.lower().endswith(".git"):
        repo = repo[:-4]

    return f"https://github.com/{owner}/{repo}.git"


def _validate_local_directory(target: str) -> Path:
    """Validate and resolve a local repository directory."""
    path = Path(target).expanduser().resolve()

    if not path.exists():
        raise RepositoryLoadError(
            f"Repository path does not exist: {path}"
        )

    if not path.is_dir():
        raise RepositoryLoadError(
            f"Repository target is not a directory: {path}"
        )

    return path


def _clone_public_repository(
    url: str,
    destination: Path,
) -> None:
    """Clone a public GitHub repository into destination."""
    try:
        completed = subprocess.run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                url,
                str(destination),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

    except FileNotFoundError as exc:
        raise RepositoryLoadError(
            "Git is required to scan a GitHub repository."
        ) from exc

    except subprocess.TimeoutExpired as exc:
        raise RepositoryLoadError(
            "GitHub repository clone timed out after 120 seconds."
        ) from exc

    if completed.returncode != 0:
        message = (
            completed.stderr.strip()
            or completed.stdout.strip()
            or "unknown Git error"
        )

        raise RepositoryLoadError(
            f"Could not clone GitHub repository: {message}"
        )


@contextmanager
def load_repository(target: str):
    """
    Resolve a local directory or public GitHub repository URL.

    Local directories are yielded directly and are not deleted.

    GitHub repositories are cloned into a temporary directory and
    automatically removed when the context exits.
    """
    if is_github_url(target):
        normalized_url = normalize_github_url(target)

        temp_root = Path(
            tempfile.mkdtemp(
                prefix="releaseguard-"
            )
        )

        repository_path = temp_root / "repository"

        try:
            _clone_public_repository(
                normalized_url,
                repository_path,
            )

            yield repository_path

        finally:
            shutil.rmtree(
                temp_root,
                ignore_errors=True,
            )

        return

    yield _validate_local_directory(target)