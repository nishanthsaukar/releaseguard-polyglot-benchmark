"""Collect and normalise evidence from test run results."""

from __future__ import annotations

from releaseguard.models.core import (
    Language,
    ProjectInfo,
    TestRunResult,
)
from releaseguard.parsers.pytest_parser import parse_pytest


def collect_evidence(results: list[TestRunResult]) -> list[TestRunResult]:
    """Parse raw test output for each result and return enriched results."""
    enriched = []
    for result in results:
        if result.project.language == Language.PYTHON and result.tooling_available:
            result = parse_pytest(result)
        enriched.append(result)
    return enriched
