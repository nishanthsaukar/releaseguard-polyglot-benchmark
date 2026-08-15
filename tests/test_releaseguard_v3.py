"""Unit tests for ReleaseGuard v0.3 — class-field inspection and Defect #2 evidence.

Tests cover:
  - ClassFieldInspectionResult dataclass shape
  - inspect_class_field: locates a Pydantic field and parses Field(...) constraints
  - inspect_class_field: handles missing file, missing class, missing field gracefully
  - inspect_class_field: handles syntax errors gracefully
  - inspect_class_field: path resolution (subdirectory)
  - _enrich_validation_with_field_evidence: appends TaskCreate.title evidence
  - _enrich_validation_with_field_evidence: no-op without repo_path
  - _enrich_validation_with_field_evidence: no-op for non-Python projects
  - _enrich_validation_with_field_evidence: deduplicates across multiple failures
  - Integrated analyzer: identifies TaskCreate.title and max_length=256 for Defect #2

These tests do NOT modify or reference any benchmark application code.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from releaseguard.models.core import (
    FindingCategory,
    Language,
    ProjectInfo,
    SourceEvidence,
    Severity,
    TestFailure,
    TestRunResult,
)
from releaseguard.source.inspector import (
    ClassFieldInspectionResult,
    inspect_class_field,
)
from releaseguard.analyzer.rules import (
    _enrich_validation_with_field_evidence,
    analyze,
)


# ===========================================================================
# Shared helpers
# ===========================================================================

def _write(tmp_path: Path, filename: str, content: str) -> None:
    """Write a dedented source file under tmp_path."""
    p = tmp_path / filename
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(content))


def _make_proj(
    lang: Language = Language.PYTHON,
    evidence_files: list[str] | None = None,
) -> ProjectInfo:
    return ProjectInfo(
        language=lang,
        confidence=0.9,
        evidence_files=evidence_files or [],
    )


def _make_run(
    failures: list[TestFailure],
    evidence_files: list[str] | None = None,
) -> TestRunResult:
    proj = _make_proj(evidence_files=evidence_files or [])
    return TestRunResult(
        project=proj,
        command="pytest -v",
        exit_code=1,
        stdout="",
        stderr="",
        duration_seconds=1.0,
        total=len(failures) + 5,
        passed=5,
        failed=len(failures),
        failures=failures,
    )


# ===========================================================================
# 1.  ClassFieldInspectionResult dataclass
# ===========================================================================

class TestClassFieldInspectionResultDataclass:
    """Basic structural tests for ClassFieldInspectionResult."""

    def test_default_unavailable(self):
        r = ClassFieldInspectionResult()
        assert r.available is False
        assert r.field_constraints == {}
        assert r.parse_error is None

    def test_fields_set_correctly(self):
        r = ClassFieldInspectionResult(
            available=True,
            source_file="app/main.py",
            class_name="TaskCreate",
            field_name="title",
            source_line=10,
            field_constraints={"max_length": 256, "min_length": 1},
        )
        assert r.available is True
        assert r.class_name == "TaskCreate"
        assert r.field_name == "title"
        assert r.source_line == 10
        assert r.field_constraints["max_length"] == 256


# ===========================================================================
# 2.  inspect_class_field — success cases
# ===========================================================================

class TestInspectClassFieldSuccess:
    """Test that inspect_class_field correctly locates and parses Pydantic fields."""

    def test_finds_field_and_parses_max_length(self, tmp_path):
        _write(tmp_path, "app/main.py", """\
            from pydantic import BaseModel, Field

            class TaskCreate(BaseModel):
                title: str = Field(..., min_length=1, max_length=256)
        """)
        result = inspect_class_field(tmp_path, "app/main.py", "TaskCreate", "title")
        assert result.available is True
        assert result.class_name == "TaskCreate"
        assert result.field_name == "title"
        assert result.field_constraints.get("max_length") == 256
        assert result.field_constraints.get("min_length") == 1

    def test_source_excerpt_contains_field_definition(self, tmp_path):
        _write(tmp_path, "app/main.py", """\
            from pydantic import BaseModel, Field

            class TaskCreate(BaseModel):
                title: str = Field(..., min_length=1, max_length=256)
        """)
        result = inspect_class_field(tmp_path, "app/main.py", "TaskCreate", "title")
        assert result.available is True
        assert result.source_excerpt is not None
        assert "max_length" in result.source_excerpt

    def test_source_line_is_correct(self, tmp_path):
        _write(tmp_path, "app/main.py", """\
            from pydantic import BaseModel, Field

            class TaskCreate(BaseModel):
                title: str = Field(..., min_length=1, max_length=256)
        """)
        result = inspect_class_field(tmp_path, "app/main.py", "TaskCreate", "title")
        assert result.available is True
        # Line 4 is `title: str = Field(...)` (1-based)
        assert result.source_line == 4

    def test_finds_second_field_in_class(self, tmp_path):
        _write(tmp_path, "app/main.py", """\
            from pydantic import BaseModel, Field

            class TaskCreate(BaseModel):
                title: str = Field(..., max_length=256)
                priority: int = Field(default=0, ge=0, le=10)
        """)
        result = inspect_class_field(tmp_path, "app/main.py", "TaskCreate", "priority")
        assert result.available is True
        assert result.field_name == "priority"
        assert result.field_constraints.get("ge") == 0
        assert result.field_constraints.get("le") == 10

    def test_finds_field_in_second_class(self, tmp_path):
        _write(tmp_path, "app/main.py", """\
            from pydantic import BaseModel, Field

            class TaskCreate(BaseModel):
                title: str = Field(..., max_length=256)

            class TaskUpdate(BaseModel):
                title: str = Field(..., max_length=255)
        """)
        result = inspect_class_field(tmp_path, "app/main.py", "TaskUpdate", "title")
        assert result.available is True
        assert result.class_name == "TaskUpdate"
        assert result.field_constraints.get("max_length") == 255

    def test_no_constraints_when_field_has_no_field_call(self, tmp_path):
        _write(tmp_path, "app/main.py", """\
            from pydantic import BaseModel

            class Simple(BaseModel):
                name: str
        """)
        result = inspect_class_field(tmp_path, "app/main.py", "Simple", "name")
        assert result.available is True
        assert result.field_constraints == {}

    def test_resolves_subdirectory_path(self, tmp_path):
        _write(tmp_path, "python-app/app/main.py", """\
            from pydantic import BaseModel, Field

            class TaskCreate(BaseModel):
                title: str = Field(..., max_length=256)
        """)
        result = inspect_class_field(
            tmp_path, "python-app/app/main.py", "TaskCreate", "title"
        )
        assert result.available is True
        assert result.field_constraints.get("max_length") == 256

    def test_path_suffix_resolution(self, tmp_path):
        """app/main.py resolves even when file is under python-app/app/main.py."""
        _write(tmp_path, "python-app/app/main.py", """\
            from pydantic import BaseModel, Field

            class TaskCreate(BaseModel):
                title: str = Field(..., max_length=99)
        """)
        # Inspector should resolve "app/main.py" via suffix matching
        result = inspect_class_field(tmp_path, "app/main.py", "TaskCreate", "title")
        assert result.available is True
        assert result.field_constraints.get("max_length") == 99


# ===========================================================================
# 3.  inspect_class_field — error / not-found cases
# ===========================================================================

class TestInspectClassFieldErrors:
    """Test graceful failure modes of inspect_class_field."""

    def test_returns_unavailable_when_file_missing(self, tmp_path):
        result = inspect_class_field(tmp_path, "nonexistent.py", "Foo", "bar")
        assert result.available is False
        assert result.parse_error is not None

    def test_returns_unavailable_when_class_missing(self, tmp_path):
        _write(tmp_path, "app/main.py", """\
            from pydantic import BaseModel

            class Other(BaseModel):
                name: str
        """)
        result = inspect_class_field(tmp_path, "app/main.py", "Missing", "name")
        assert result.available is False
        assert result.parse_error is not None

    def test_returns_unavailable_when_field_missing(self, tmp_path):
        _write(tmp_path, "app/main.py", """\
            from pydantic import BaseModel, Field

            class TaskCreate(BaseModel):
                title: str = Field(..., max_length=256)
        """)
        result = inspect_class_field(tmp_path, "app/main.py", "TaskCreate", "nonexistent")
        assert result.available is False
        assert result.parse_error is not None

    def test_handles_syntax_error_gracefully(self, tmp_path):
        p = tmp_path / "bad.py"
        p.write_text("class Broken(:\n    title: str")
        result = inspect_class_field(tmp_path, "bad.py", "Broken", "title")
        assert result.available is False
        assert result.parse_error is not None


# ===========================================================================
# 4.  _enrich_validation_with_field_evidence
# ===========================================================================

class TestEnrichValidationWithFieldEvidence:
    """Test the field-constraint enrichment step for validation findings."""

    def _write_create_model(self, tmp_path: Path, max_length: int = 256) -> None:
        _write(tmp_path, "app/main.py", f"""\
            from pydantic import BaseModel, Field

            class TaskCreate(BaseModel):
                title: str = Field(..., min_length=1, max_length={max_length})

            def create_task(payload):
                pass
        """)

    def test_appends_field_evidence_for_create_title_failure(self, tmp_path):
        self._write_create_model(tmp_path)
        failure = TestFailure(name="TestCreateTask::test_create_title_too_long_returns_422")
        run = _make_run([failure], evidence_files=["app/main.py"])
        result = _enrich_validation_with_field_evidence(
            [failure], run, tmp_path, existing=[]
        )
        assert len(result) == 1
        ev = result[0]
        assert ev.available is True
        assert "max_length" in (ev.source_excerpt or "")
        assert "256" in (ev.source_excerpt or "")

    def test_field_evidence_has_correct_class_and_constraints_in_reasoning(self, tmp_path):
        self._write_create_model(tmp_path, max_length=256)
        failure = TestFailure(name="TestCreateTask::test_create_title_too_long_returns_422")
        run = _make_run([failure], evidence_files=["app/main.py"])
        result = _enrich_validation_with_field_evidence(
            [failure], run, tmp_path, existing=[]
        )
        assert result
        ev = result[0]
        assert ev.reasoning is not None
        assert "TaskCreate" in ev.reasoning
        assert "title" in ev.reasoning
        assert "max_length" in ev.reasoning

    def test_returns_existing_unchanged_when_no_repo_path(self):
        failure = TestFailure(name="TestCreateTask::test_create_title_too_long_returns_422")
        existing = [SourceEvidence(available=False, evidence_method="none")]
        run = _make_run([failure])
        result = _enrich_validation_with_field_evidence(
            [failure], run, repo_path=None, existing=existing
        )
        assert result == existing

    def test_returns_existing_unchanged_for_non_python_project(self, tmp_path):
        failure = TestFailure(name="TestCreateTask::test_create_title_too_long_returns_422")
        proj = _make_proj(lang=Language.GO)
        run = TestRunResult(
            project=proj,
            command="go test ./...",
            exit_code=1,
            stdout="",
            stderr="",
            duration_seconds=1.0,
            total=2,
            passed=1,
            failed=1,
            failures=[failure],
        )
        existing: list[SourceEvidence] = []
        result = _enrich_validation_with_field_evidence(
            [failure], run, tmp_path, existing=existing
        )
        assert result == existing

    def test_deduplicates_across_multiple_matching_failures(self, tmp_path):
        """Two failures both matching TaskCreate.title should produce only one field evidence."""
        self._write_create_model(tmp_path)
        failures = [
            TestFailure(name="TestCreateTask::test_create_title_too_long_returns_422"),
            TestFailure(name="TestCreateTask::test_create_title_at_boundary"),
        ]
        run = _make_run(failures, evidence_files=["app/main.py"])
        result = _enrich_validation_with_field_evidence(
            failures, run, tmp_path, existing=[]
        )
        # Only one entry for TaskCreate.title regardless of how many failures matched
        assert len(result) == 1

    def test_appends_to_existing_list(self, tmp_path):
        """New field evidence is appended, not replacing existing entries."""
        self._write_create_model(tmp_path)
        failure = TestFailure(name="TestCreateTask::test_create_title_too_long_returns_422")
        existing = [SourceEvidence(available=True, source_file="app/main.py", evidence_method="traceback")]
        run = _make_run([failure], evidence_files=["app/main.py"])
        result = _enrich_validation_with_field_evidence(
            [failure], run, tmp_path, existing=existing
        )
        assert len(result) == 2
        assert result[0] is existing[0]  # original preserved first

    def test_no_field_evidence_when_no_matching_source_file(self, tmp_path):
        """When no source file contains TaskCreate, nothing is appended."""
        failure = TestFailure(name="TestCreateTask::test_create_title_too_long_returns_422")
        run = _make_run([failure], evidence_files=[])
        result = _enrich_validation_with_field_evidence(
            [failure], run, tmp_path, existing=[]
        )
        assert result == []


# ===========================================================================
# 5.  Integrated analyzer — Defect #2 evidence path
# ===========================================================================

class TestAnalyzerDefect2Evidence:
    """Integrated tests: the analyzer identifies TaskCreate.title and max_length."""

    def _write_defect_app(self, tmp_path: Path, max_length: int = 256) -> None:
        """Write a minimal app with the Defect #2 mutation applied."""
        _write(tmp_path, "app/main.py", f"""\
            from pydantic import BaseModel, Field

            class TaskCreate(BaseModel):
                title: str = Field(..., min_length=1, max_length={max_length})

            class TaskUpdate(BaseModel):
                title: str = Field(..., min_length=1, max_length=255)

            def create_task(payload):
                return {{"title": payload.title}}
        """)
        _write(tmp_path, "requirements.txt", "fastapi\npydantic\n")

    def test_analyzer_finds_max_length_in_source_evidence(self, tmp_path):
        self._write_defect_app(tmp_path, max_length=256)
        failure = TestFailure(
            name="TestCreateTask::test_create_title_too_long_returns_422",
            expected_value="422",
            actual_value="201",
        )
        proj = ProjectInfo(
            language=Language.PYTHON,
            confidence=0.9,
            evidence_files=["requirements.txt", "app/main.py"],
        )
        run = TestRunResult(
            project=proj,
            command="pytest -v",
            exit_code=1,
            stdout="", stderr="",
            duration_seconds=1.0,
            total=10, passed=9, failed=1,
            failures=[failure],
        )
        findings = analyze([run], repo_path=tmp_path)
        contract_findings = [f for f in findings if f.category == FindingCategory.API_CONTRACT]
        assert contract_findings, "Expected an API_CONTRACT finding"
        f = contract_findings[0]

        # At least one source evidence entry must reference TaskCreate.title directly
        field_evidences = [
            ev for ev in f.source_evidence
            if ev.available and ev.source_excerpt and "max_length" in ev.source_excerpt
        ]
        assert field_evidences, (
            "Expected source_evidence to contain an entry with max_length from TaskCreate.title"
        )

    def test_analyzer_reasoning_mentions_max_length_value(self, tmp_path):
        """The reasoning text must mention the specific max_length value."""
        self._write_defect_app(tmp_path, max_length=256)
        failure = TestFailure(
            name="TestCreateTask::test_create_title_too_long_returns_422",
            expected_value="422",
            actual_value="201",
        )
        proj = ProjectInfo(
            language=Language.PYTHON,
            confidence=0.9,
            evidence_files=["requirements.txt", "app/main.py"],
        )
        run = TestRunResult(
            project=proj,
            command="pytest -v",
            exit_code=1,
            stdout="", stderr="",
            duration_seconds=1.0,
            total=10, passed=9, failed=1,
            failures=[failure],
        )
        findings = analyze([run], repo_path=tmp_path)
        contract_findings = [f for f in findings if f.category == FindingCategory.API_CONTRACT]
        assert contract_findings
        f = contract_findings[0]
        # Reasoning must mention max_length and/or 256
        reasoning = f.reasoning or ""
        assert "max_length" in reasoning or "256" in reasoning, (
            f"Reasoning should reference max_length constraint; got: {reasoning!r}"
        )

    def test_analyzer_identifies_class_name_in_evidence(self, tmp_path):
        """Source evidence reasoning must name 'TaskCreate' for Defect #2."""
        self._write_defect_app(tmp_path, max_length=256)
        failure = TestFailure(
            name="TestCreateTask::test_create_title_too_long_returns_422",
            expected_value="422",
            actual_value="201",
        )
        proj = ProjectInfo(
            language=Language.PYTHON,
            confidence=0.9,
            evidence_files=["requirements.txt", "app/main.py"],
        )
        run = TestRunResult(
            project=proj,
            command="pytest -v",
            exit_code=1,
            stdout="", stderr="",
            duration_seconds=1.0,
            total=10, passed=9, failed=1,
            failures=[failure],
        )
        findings = analyze([run], repo_path=tmp_path)
        contract_findings = [f for f in findings if f.category == FindingCategory.API_CONTRACT]
        assert contract_findings
        f = contract_findings[0]

        # At least one source evidence entry's reasoning must name TaskCreate
        evidences_with_class = [
            ev for ev in f.source_evidence
            if ev.available and "TaskCreate" in (ev.reasoning or "")
        ]
        assert evidences_with_class, (
            "Expected at least one source_evidence entry to mention 'TaskCreate' in reasoning"
        )

    def test_analyzer_still_works_without_repo_path(self):
        """Analyzer must still produce a finding when repo_path is None."""
        failure = TestFailure(
            name="TestCreateTask::test_create_title_too_long_returns_422",
            expected_value="422",
            actual_value="201",
        )
        proj = ProjectInfo(language=Language.PYTHON, confidence=0.9)
        run = TestRunResult(
            project=proj,
            command="pytest -v",
            exit_code=1,
            stdout="", stderr="",
            duration_seconds=1.0,
            total=10, passed=9, failed=1,
            failures=[failure],
        )
        findings = analyze([run], repo_path=None)
        contract_findings = [f for f in findings if f.category == FindingCategory.API_CONTRACT]
        assert contract_findings
