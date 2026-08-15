"""Detect languages and projects present in a repository."""

from __future__ import annotations

from pathlib import Path

from releaseguard.models.core import Language, ProjectInfo


# ---------------------------------------------------------------------------
# Detection rules
# ---------------------------------------------------------------------------
# Each rule is a tuple of:
#   (Language, definitive_files, glob_patterns, weight)
#
# definitive_files: filenames that, if present at repo root or within any
#                   sub-directory, strongly indicate the language.
# glob_patterns:    patterns searched recursively; count > 0 contributes.
# weight:           confidence contribution per definitive file found.

_RULES: list[tuple[Language, list[str], list[str], float]] = [
    (
        Language.PYTHON,
        ["requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile"],
        ["**/*.py"],
        0.9,
    ),
    (
        Language.RUST,
        ["Cargo.toml", "Cargo.lock"],
        ["**/*.rs"],
        0.95,
    ),
    (
        Language.GO,
        ["go.mod", "go.sum"],
        ["**/*.go"],
        0.95,
    ),
    (
        Language.NODE,
        ["package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"],
        ["**/*.js", "**/*.ts"],
        0.9,
    ),
    (
        Language.JAVA,
        ["pom.xml", "build.gradle", "build.gradle.kts", "gradlew", "mvnw"],
        ["**/*.java"],
        0.95,
    ),
]

# Directories that should never be searched for evidence
_SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    "target", ".pytest_cache", ".mypy_cache", "dist", "build",
    ".tox", ".eggs", "site-packages",
}


def detect_projects(repo_path: Path) -> list[ProjectInfo]:
    """Return one ProjectInfo per detected language/project.

    Searches *all* sub-directories so a polyglot monorepo is handled.
    Each language produces at most one ProjectInfo, even if multiple
    sub-projects exist (e.g., two Python packages).
    """
    results: list[ProjectInfo] = []

    # Enumerate all candidate files once (avoids re-walking for each language)
    all_files = _walk_files(repo_path)
    rel_files = [str(f.relative_to(repo_path)) for f in all_files]
    # Map filename → list of relative paths (multiple sub-projects may share filename)
    rel_by_name: dict[str, list[str]] = {}
    for rf in rel_files:
        name = Path(rf).name
        rel_by_name.setdefault(name, []).append(rf)

    for language, definitive, globs, weight in _RULES:
        evidence: list[str] = []

        # Check definitive filenames — store full relative path, not just filename
        for def_file in definitive:
            if def_file in rel_by_name:
                # Take the first occurrence (shallowest path wins due to os.walk order)
                evidence.append(rel_by_name[def_file][0])

        # Check glob patterns (only count if at least one match)
        for pattern in globs:
            suffix = pattern.lstrip("**/")  # extract extension, e.g. .py
            matches = [f for f in rel_files if f.endswith(suffix)]
            if matches:
                # Record only a sample (first match) to keep evidence compact
                evidence.append(matches[0])
                break  # one pattern match is enough per language

        if not evidence:
            continue

        # Confidence: definitive file found → high; only source file found → lower
        has_definitive = any(
            Path(e).name in definitive for e in evidence
        )
        confidence = weight if has_definitive else 0.4

        results.append(
            ProjectInfo(
                language=language,
                confidence=confidence,
                evidence_files=evidence,
            )
        )

    return results


def _walk_files(root: Path) -> list[Path]:
    """Walk the directory tree, skipping irrelevant directories."""
    files: list[Path] = []
    try:
        for entry in root.rglob("*"):
            # Skip entries inside unwanted directories
            parts = entry.parts
            if any(part in _SKIP_DIRS for part in parts):
                continue
            if entry.is_file():
                files.append(entry)
    except PermissionError:
        pass
    return files
