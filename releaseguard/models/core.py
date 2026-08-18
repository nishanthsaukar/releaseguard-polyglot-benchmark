"""Core typed models for ReleaseGuard."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Source evidence
# ---------------------------------------------------------------------------

@dataclass
class SourceEvidence:
    """Source-code evidence associated with a finding.

    All fields are optional — when evidence cannot be found, the
    ``available`` flag is False and the other fields will be empty/None.
    Callers must never fabricate values; leave fields at their defaults
    when the information cannot be reliably determined.
    """

    available: bool = False          # True only when at least file is known

    source_file: Optional[str] = None        # relative path in repo
    source_function: Optional[str] = None    # function/method name
    source_line: Optional[int] = None        # 1-based line number
    source_line_end: Optional[int] = None    # inclusive end line (for ranges)
    source_excerpt: Optional[str] = None     # a few lines of actual source
    reasoning: Optional[str] = None          # deterministic explanation

    # How the evidence was obtained: "traceback", "ast", "heuristic", "none"
    evidence_method: str = "none"


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class Language(str, Enum):
    PYTHON = "Python"
    RUST = "Rust"
    GO = "Go"
    NODE = "Node.js"
    JAVA = "Java"
    UNKNOWN = "Unknown"


class Severity(str, Enum):
    BLOCKER = "BLOCKER"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class FindingCategory(str, Enum):
    SECURITY = "security"
    FUNCTIONAL = "functional"
    API_CONTRACT = "api_contract"
    CONFIGURATION = "configuration"
    TESTING = "testing"
    TOOLING = "tooling"
    UNKNOWN = "unknown"


class ReleaseDecision(str, Enum):
    READY = "READY"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    BLOCKED = "BLOCKED"


# ---------------------------------------------------------------------------
# Project / language detection
# ---------------------------------------------------------------------------

@dataclass
class ProjectInfo:
    """Evidence of a detected project/language in the repository."""

    language: Language
    confidence: float          # 0.0 – 1.0
    evidence_files: list[str] = field(default_factory=list)
    test_command: Optional[str] = None
    test_command_available: Optional[bool] = None  # None = not yet checked


# ---------------------------------------------------------------------------
# Test execution
# ---------------------------------------------------------------------------

@dataclass
class TestFailure:
    """A single failing test case."""

    name: str
    error_text: str = ""
    file_path: Optional[str] = None

    # Traceback-derived location of the assertion that failed
    # (the innermost frame in the test itself, not inside the app)
    tb_file: Optional[str] = None   # relative path
    tb_line: Optional[int] = None   # 1-based line number

    # Expected / actual values extracted from assertion output
    expected_value: Optional[str] = None
    actual_value: Optional[str] = None


@dataclass
class TestRunResult:
    """Outcome of executing a test suite."""

    project: ProjectInfo
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float

    total: Optional[int] = None
    passed: Optional[int] = None
    failed: Optional[int] = None
    skipped: Optional[int] = None
    failures: list[TestFailure] = field(default_factory=list)

    # Human-readable explanation when the command couldn't even run
    unavailable_reason: Optional[str] = None

    # Set when the test runner started successfully but could not complete
    # normal test collection/execution (for example, an import/collection error).
    # This is distinct from a real failing test and from missing tooling.
    execution_error: Optional[str] = None

    @property
    def tooling_available(self) -> bool:
        return self.unavailable_reason is None

    @property
    def has_failures(self) -> bool:
        """Return True only when actual test cases are known to have failed."""
        if self.failed is not None:
            return self.failed > 0
        return False


# ---------------------------------------------------------------------------
# Risk findings
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    """A single release-risk finding."""

    category: FindingCategory
    severity: Severity
    title: str
    summary: str
    evidence: str
    affected_files: list[str] = field(default_factory=list)
    affected_tests: list[str] = field(default_factory=list)
    confidence: float = 1.0     # 0.0 – 1.0

    # Source-code evidence (may be empty if static analysis found nothing)
    source_evidence: list[SourceEvidence] = field(default_factory=list)
    # Deterministic root-cause explanation
    reasoning: Optional[str] = None


# ---------------------------------------------------------------------------
# Top-level report
# ---------------------------------------------------------------------------

@dataclass
class RepositoryReport:
    """Complete release-readiness report for a repository."""

    repository_path: str
    projects: list[ProjectInfo] = field(default_factory=list)
    test_runs: list[TestRunResult] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    decision: ReleaseDecision = ReleaseDecision.READY
