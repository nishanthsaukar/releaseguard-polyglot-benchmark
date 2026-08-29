"""Core typed models for ReleaseGuard."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Language(str, Enum):
    """Supported project languages."""

    PYTHON = "python"
    NODE = "node"
    JAVA = "java"
    GO = "go"
    RUST = "rust"


class Severity(str, Enum):
    """Severity levels for release-risk findings."""

    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    BLOCKER = "BLOCKER"

    # Compatibility with older/newer rules.
    CRITICAL = "CRITICAL"


class FindingCategory(str, Enum):
    """Categories of release-risk findings."""

    # Generic application behavior problems.
    FUNCTIONAL = "FUNCTIONAL"

    # Test execution and test-suite problems.
    TESTING = "TESTING"
    TEST_FAILURE = "TEST_FAILURE"

    # Tool/runtime/dependency problems.
    TOOLING = "TOOLING"

    # Authorization and access-control problems.
    AUTHORIZATION = "AUTHORIZATION"

    # API/data validation problems.
    VALIDATION = "VALIDATION"

    # Explicit API contract violations.
    API_CONTRACT = "API_CONTRACT"

    # Incorrect state changes.
    STATE_TRANSITION = "STATE_TRANSITION"

    # Security-related problems.
    SECURITY = "SECURITY"

    # Fallback category.
    UNKNOWN = "UNKNOWN"


class ReleaseDecision(str, Enum):
    """Final release-readiness decision."""

    READY = "READY"

    REVIEW_REQUIRED = "REVIEW_REQUIRED"

    BLOCKED = "BLOCKED"

    # Backward compatibility.
    NOT_READY = "NOT_READY"

    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# Source evidence
# ---------------------------------------------------------------------------


@dataclass
class SourceEvidence:
    """Source-code evidence supporting a finding."""

    # Whether source evidence could actually be located.
    available: bool = False

    # Relative source file path.
    source_file: Optional[str] = None

    # Function or method containing the evidence, when known.
    source_function: Optional[str] = None

    # Starting source line containing the evidence.
    source_line: Optional[int] = None

    # Ending source line containing the evidence.
    source_line_end: Optional[int] = None

    # Relevant source-code excerpt.
    source_excerpt: Optional[str] = None

    # How the evidence was discovered.
    #
    # Examples:
    #   "traceback"
    #   "heuristic"
    #   "ast"
    #   "none"
    evidence_method: str = "none"

    # Explanation of why this source location is relevant.
    reasoning: Optional[str] = None


# ---------------------------------------------------------------------------
# Project / language detection
# ---------------------------------------------------------------------------


@dataclass
class ProjectInfo:
    """Information about a detected project inside a repository.

    ``project_path`` is relative to the repository root.
    """

    language: Language
    confidence: float

    # Files used as evidence when detecting this project.
    evidence_files: list[str] = field(default_factory=list)

    # Relative directory containing the actual project.
    project_path: str = "."

    # Detected command used to run the project's tests.
    test_command: Optional[str] = None

    # Whether the required test tool is available.
    # None means availability has not yet been checked.
    test_command_available: Optional[bool] = None


# ---------------------------------------------------------------------------
# Test execution
# ---------------------------------------------------------------------------


@dataclass
class TestFailure:
    """A single failing test case."""

    name: str

    error_text: str = ""

    # Test file path, when known.
    file_path: Optional[str] = None

    # Traceback-derived source location.
    tb_file: Optional[str] = None
    tb_line: Optional[int] = None

    # Expected / actual values extracted from assertion output.
    expected_value: Optional[str] = None
    actual_value: Optional[str] = None


@dataclass
class TestRunResult:
    """Outcome of executing a project's test suite."""

    project: ProjectInfo

    # Command that was actually executed.
    command: str

    # Process exit code.
    exit_code: int

    # Raw command output.
    stdout: str
    stderr: str

    # Execution duration in seconds.
    duration_seconds: float

    # Parsed test counts.
    total: Optional[int] = None
    passed: Optional[int] = None
    failed: Optional[int] = None
    skipped: Optional[int] = None

    # Individual failing tests.
    failures: list[TestFailure] = field(default_factory=list)

    # Reason the command could not be executed.
    unavailable_reason: Optional[str] = None

    # Reason the test runner started but could not complete normally.
    execution_error: Optional[str] = None

    @property
    def tooling_available(self) -> bool:
        """Return True when the test command could be attempted."""

        return self.unavailable_reason is None

    @property
    def has_failures(self) -> bool:
        """Return True only when actual test cases are known to have failed."""

        return self.failed is not None and self.failed > 0

    @property
    def has_known_test_count(self) -> bool:
        """Return True when test counts were successfully determined."""

        return self.total is not None


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

    confidence: float = 1.0

    # Source-code evidence supporting this finding.
    source_evidence: list[SourceEvidence] = field(default_factory=list)

    # Deterministic explanation of why this finding was produced.
    reasoning: Optional[str] = None

    # Evidence-grounded explanation of the most likely underlying cause.
    root_cause: Optional[str] = None

    # Deterministic recommendation for resolving the finding.
    recommended_fix: Optional[str] = None


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