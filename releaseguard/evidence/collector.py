"""Collect and normalise evidence from test run results."""

from __future__ import annotations

from releaseguard.models.core import Language, TestRunResult
from releaseguard.parsers.pytest_parser import parse_pytest
from releaseguard.parsers.node_parser import parse_node
from releaseguard.parsers.go_parser import parse_go
from releaseguard.parsers.rust_parser import parse_rust
from releaseguard.parsers.java_parser import parse_java


_PARSERS = {
    Language.PYTHON: parse_pytest,
    Language.NODE:   parse_node,
    Language.GO:     parse_go,
    Language.RUST:   parse_rust,
    Language.JAVA:   parse_java,
}


def collect_evidence(results: list[TestRunResult]) -> list[TestRunResult]:
    """Parse raw test output for each result and return enriched results."""
    enriched = []
    for result in results:
        parser = _PARSERS.get(result.project.language)
        if parser is not None and result.tooling_available:
            result = parser(result)
        enriched.append(result)
    return enriched
