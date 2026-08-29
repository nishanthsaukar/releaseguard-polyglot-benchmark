"""Detect projects and languages present in a repository."""

from __future__ import annotations

from pathlib import Path

from releaseguard.models.core import Language, ProjectInfo


# A real project is primarily identified by one of these marker files.
_PROJECT_MARKERS: dict[Language, list[str]] = {
    Language.PYTHON: [
        "pyproject.toml",
        "requirements.txt",
        "setup.py",
        "setup.cfg",
        "Pipfile",
    ],
    Language.RUST: [
        "Cargo.toml",
    ],
    Language.GO: [
        "go.mod",
    ],
    Language.NODE: [
        "package.json",
    ],
    Language.JAVA: [
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
    ],
}


_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "target",
    ".pytest_cache",
    ".mypy_cache",
    "dist",
    "build",
    ".tox",
    ".eggs",
    "site-packages",
}


def detect_projects(repo_path: Path) -> list[ProjectInfo]:
    """Detect actual projects inside *repo_path*.

    Each project is identified from a definitive project marker such as
    ``pyproject.toml``, ``package.json`` or ``Cargo.toml``.

    Unlike the old implementation, merely finding a ``.py`` or ``.js`` file
    does not create a project. This prevents false positives in polyglot
    repositories.
    """

    results: list[ProjectInfo] = []

    all_files = _walk_files(repo_path)

    for language, markers in _PROJECT_MARKERS.items():
        for marker in markers:
            marker_files = [
                file
                for file in all_files
                if file.name == marker
            ]

            for marker_file in marker_files:
                project_dir = marker_file.parent

                relative_dir = project_dir.relative_to(repo_path)

                project_path = (
                    "."
                    if str(relative_dir) == "."
                    else str(relative_dir)
                )

                relative_marker = str(
                    marker_file.relative_to(repo_path)
                )

                # Avoid duplicate projects when a directory contains
                # multiple marker files for the same language.
                if _project_exists(
                    results,
                    language,
                    project_path,
                ):
                    continue

                results.append(
                    ProjectInfo(
                        language=language,
                        confidence=0.95,
                        evidence_files=[relative_marker],
                        project_path=project_path,
                    )
                )

    return results


def _project_exists(
    projects: list[ProjectInfo],
    language: Language,
    project_path: str,
) -> bool:
    """Return True when this language/project directory already exists."""

    return any(
        project.language == language
        and project.project_path == project_path
        for project in projects
    )


def _walk_files(root: Path) -> list[Path]:
    """Walk repository files while skipping generated/dependency directories."""

    files: list[Path] = []

    try:
        for entry in root.rglob("*"):
            if any(part in _SKIP_DIRS for part in entry.parts):
                continue

            if entry.is_file():
                files.append(entry)

    except PermissionError:
        pass

    return files