"""Unit tests for the polyglot test-output parsers.

Covers:
  - node_parser  : Node built-in runner (plain + ℹ prefix + ANSI), Jest, Mocha
  - go_parser    : verbose (-v) output, non-verbose, build failure
  - rust_parser  : cargo test summary, verbose, compilation error
  - java_parser  : Maven Surefire, Gradle
"""

from __future__ import annotations

import textwrap

import pytest

from releaseguard.models.core import Language, ProjectInfo, TestRunResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _result(lang: Language, stdout: str = "", stderr: str = "", exit_code: int = 0) -> TestRunResult:
    proj = ProjectInfo(language=lang, confidence=0.9)
    return TestRunResult(
        project=proj,
        command="test",
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_seconds=0.1,
    )


# ===========================================================================
# Node parser
# ===========================================================================

class TestNodeParser:
    """Tests for releaseguard/parsers/node_parser.py."""

    def _run(self, stdout="", stderr="", exit_code=0):
        from releaseguard.parsers.node_parser import parse_node
        return parse_node(_result(Language.NODE, stdout, stderr, exit_code))

    # --- Node built-in runner: plain ASCII (no ℹ prefix) ---

    def test_node_plain_all_pass(self):
        stdout = textwrap.dedent("""\
            tests 2
            pass 2
            fail 0
            skipped 0
        """)
        r = self._run(stdout=stdout)
        assert r.total == 2
        assert r.passed == 2
        assert r.failed == 0
        assert r.skipped == 0

    def test_node_plain_with_failure(self):
        stdout = textwrap.dedent("""\
            tests 3
            pass 2
            fail 1
            skipped 0
        """)
        r = self._run(stdout=stdout, exit_code=1)
        assert r.total == 3
        assert r.passed == 2
        assert r.failed == 1

    # --- Node built-in runner: ℹ prefix (real Node v18+ output) ---

    def test_node_info_prefix_all_pass(self):
        stderr = textwrap.dedent("""\
            ℹ tests 2
            ℹ pass 2
            ℹ fail 0
            ℹ skipped 0
            ℹ duration_ms 12.34
        """)
        r = self._run(stderr=stderr)
        assert r.total == 2
        assert r.passed == 2
        assert r.failed == 0
        assert r.skipped == 0

    def test_node_info_prefix_with_failure(self):
        stderr = textwrap.dedent("""\
            ℹ tests 5
            ℹ pass 3
            ℹ fail 2
            ℹ skipped 0
        """)
        r = self._run(stderr=stderr, exit_code=1)
        assert r.total == 5
        assert r.passed == 3
        assert r.failed == 2

    def test_node_info_prefix_with_skipped(self):
        stderr = "ℹ tests 4\nℹ pass 3\nℹ fail 0\nℹ skipped 1\n"
        r = self._run(stderr=stderr)
        assert r.total == 4
        assert r.skipped == 1

    def test_node_info_prefix_in_stdout(self):
        """ℹ lines may appear in stdout instead of stderr."""
        stdout = "ℹ tests 2\nℹ pass 2\nℹ fail 0\n"
        r = self._run(stdout=stdout)
        assert r.total == 2
        assert r.passed == 2

    # --- ANSI escape codes wrapping the ℹ prefix ---

    def test_node_ansi_wrapped_prefix(self):
        """ANSI colour codes around the ℹ symbol must be stripped before parsing."""
        ansi_info = "\x1b[34mℹ\x1b[0m"
        stderr = f"{ansi_info} tests 3\n{ansi_info} pass 3\n{ansi_info} fail 0\n"
        r = self._run(stderr=stderr)
        assert r.total == 3
        assert r.passed == 3

    # --- TAP not-ok failure lines ---

    def test_node_not_ok_failure_name_extracted(self):
        stdout = textwrap.dedent("""\
            not ok 1 - should add numbers
            tests 2
            pass 1
            fail 1
        """)
        r = self._run(stdout=stdout, exit_code=1)
        assert r.failed == 1
        assert len(r.failures) == 1
        assert "should add numbers" in r.failures[0].name

    # --- Jest ---

    def test_jest_all_pass(self):
        stdout = "Tests: 5 passed, 5 total\n"
        r = self._run(stdout=stdout)
        assert r.total == 5
        assert r.passed == 5
        assert r.failed == 0

    def test_jest_with_failures(self):
        stdout = "Tests: 2 failed, 3 passed, 5 total\n"
        r = self._run(stdout=stdout, exit_code=1)
        assert r.total == 5
        assert r.failed == 2
        assert r.passed == 3

    def test_jest_with_skipped(self):
        stdout = "Tests: 1 skipped, 4 passed, 5 total\n"
        r = self._run(stdout=stdout)
        assert r.skipped == 1
        assert r.passed == 4
        assert r.total == 5

    def test_jest_failure_bullet_extracted(self):
        stdout = textwrap.dedent("""\
            Tests: 1 failed, 1 total

              ● add > should return correct sum
        """)
        r = self._run(stdout=stdout, exit_code=1)
        assert r.failures
        assert "add > should return correct sum" in r.failures[0].name

    # --- Mocha ---

    def test_mocha_all_pass(self):
        stdout = textwrap.dedent("""\
            passing (42ms)

              3 passing
        """)
        r = self._run(stdout=stdout)
        assert r.passed == 3
        assert r.failed == 0
        assert r.total == 3

    def test_mocha_with_failure(self):
        stdout = "  4 passing (10ms)\n  1 failing\n"
        r = self._run(stdout=stdout, exit_code=1)
        assert r.passed == 4
        assert r.failed == 1
        assert r.total == 5

    def test_mocha_failure_name_extracted(self):
        stdout = textwrap.dedent("""\
              2 passing
              1 failing

              1) MyModule should work correctly
        """)
        r = self._run(stdout=stdout, exit_code=1)
        assert r.failures
        assert "MyModule should work correctly" in r.failures[0].name

    # --- Unknown output: no counts fabricated ---

    def test_no_recognisable_output_leaves_counts_none(self):
        r = self._run(stdout="some random output\n", exit_code=0)
        assert r.total is None
        assert r.passed is None
        assert r.failed is None


# ===========================================================================
# Go parser
# ===========================================================================

class TestGoParser:
    """Tests for releaseguard/parsers/go_parser.py."""

    def _run(self, stdout="", stderr="", exit_code=0):
        from releaseguard.parsers.go_parser import parse_go
        return parse_go(_result(Language.GO, stdout, stderr, exit_code))

    def test_verbose_all_pass(self):
        stdout = textwrap.dedent("""\
            --- PASS: TestAdd (0.00s)
            --- PASS: TestSub (0.00s)
            ok      example.com/mymodule  0.002s
        """)
        r = self._run(stdout=stdout)
        assert r.passed == 2
        assert r.failed == 0
        assert r.skipped == 0
        assert r.total == 2
        assert r.failures == []

    def test_verbose_with_failure(self):
        stdout = textwrap.dedent("""\
            --- PASS: TestAdd (0.00s)
            --- FAIL: TestSub (0.01s)
            FAIL    example.com/mymodule  0.011s
        """)
        r = self._run(stdout=stdout, exit_code=1)
        assert r.passed == 1
        assert r.failed == 1
        assert r.total == 2
        assert len(r.failures) == 1
        assert "TestSub" in r.failures[0].name

    def test_verbose_with_skip(self):
        stdout = textwrap.dedent("""\
            --- PASS: TestA (0.00s)
            --- SKIP: TestB (0.00s)
            ok      example.com/m  0.001s
        """)
        r = self._run(stdout=stdout)
        assert r.passed == 1
        assert r.skipped == 1
        assert r.total == 2

    def test_non_verbose_pass_leaves_counts_none(self):
        """Without -v, go test prints no individual test lines — counts stay None."""
        stdout = "ok      example.com/mymodule  0.002s\n"
        r = self._run(stdout=stdout)
        assert r.total is None
        assert r.passed is None
        assert r.failed is None
        assert r.execution_error is None

    def test_non_verbose_fail_sets_execution_error(self):
        stdout = "FAIL    example.com/mymodule  0.011s\n"
        r = self._run(stdout=stdout, exit_code=1)
        assert r.execution_error is not None
        assert "FAIL" in r.execution_error or "package" in r.execution_error.lower()

    def test_build_failure_sets_execution_error(self):
        stderr = "FAIL\texample.com/mymodule [build failed]\n"
        r = self._run(stderr=stderr, exit_code=1)
        assert r.execution_error is not None
        assert "build" in r.execution_error.lower()

    def test_multiple_pass_failures_counted(self):
        stdout = textwrap.dedent("""\
            --- PASS: TestA (0.00s)
            --- PASS: TestB (0.00s)
            --- FAIL: TestC (0.01s)
            --- FAIL: TestD (0.01s)
        """)
        r = self._run(stdout=stdout, exit_code=1)
        assert r.passed == 2
        assert r.failed == 2
        assert r.total == 4
        assert len(r.failures) == 2

    def test_no_output_leaves_counts_none(self):
        r = self._run(stdout="", stderr="")
        assert r.total is None
        assert r.passed is None


# ===========================================================================
# Rust parser
# ===========================================================================

class TestRustParser:
    """Tests for releaseguard/parsers/rust_parser.py."""

    def _run(self, stdout="", stderr="", exit_code=0):
        from releaseguard.parsers.rust_parser import parse_rust
        return parse_rust(_result(Language.RUST, stdout, stderr, exit_code))

    def test_summary_all_pass(self):
        stdout = textwrap.dedent("""\
            running 5 tests
            test a::test_one ... ok
            test a::test_two ... ok
            test b::test_three ... ok
            test b::test_four ... ok
            test c::test_five ... ok

            test result: ok. 5 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.01s
        """)
        r = self._run(stdout=stdout)
        assert r.passed == 5
        assert r.failed == 0
        assert r.skipped == 0
        assert r.total == 5
        assert r.failures == []

    def test_summary_with_failures(self):
        stdout = textwrap.dedent("""\
            running 5 tests
            test a::test_one ... ok
            test a::test_two ... FAILED
            test b::test_three ... ok

            test result: FAILED. 2 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.01s
        """)
        r = self._run(stdout=stdout, exit_code=101)
        assert r.passed == 2
        assert r.failed == 1
        assert r.total == 3
        assert len(r.failures) == 1
        assert "a::test_two" in r.failures[0].name

    def test_summary_with_ignored(self):
        stdout = textwrap.dedent("""\
            test result: ok. 3 passed; 0 failed; 2 ignored; 0 measured; 0 filtered out
        """)
        r = self._run(stdout=stdout)
        assert r.passed == 3
        assert r.skipped == 2
        assert r.total == 5

    def test_failure_error_text_extracted(self):
        stdout = textwrap.dedent("""\
            test mymod::test_bad ... FAILED

            failures:

            ---- mymod::test_bad stdout ----
            thread 'mymod::test_bad' panicked at 'assertion failed: 1 == 2'

            test result: FAILED. 0 passed; 1 failed; 0 ignored
        """)
        r = self._run(stdout=stdout, exit_code=101)
        assert r.failures
        assert "assertion" in r.failures[0].error_text.lower() or r.failures[0].error_text != ""

    def test_compilation_error_sets_execution_error(self):
        stderr = textwrap.dedent("""\
            error[E0425]: cannot find value `x` in this scope
             --> src/lib.rs:5:9
        """)
        r = self._run(stderr=stderr, exit_code=101)
        assert r.execution_error is not None
        assert "compilation" in r.execution_error.lower()

    def test_verbose_without_summary_fallback(self):
        """Parser falls back to counting individual test lines when no summary."""
        stdout = textwrap.dedent("""\
            running 2 tests
            test mod::test_a ... ok
            test mod::test_b ... ok
        """)
        r = self._run(stdout=stdout)
        assert r.passed == 2
        assert r.failed == 0
        assert r.total == 2

    def test_no_output_leaves_counts_none(self):
        r = self._run(stdout="", stderr="")
        assert r.total is None
        assert r.passed is None


# ===========================================================================
# Java parser
# ===========================================================================

class TestJavaParser:
    """Tests for releaseguard/parsers/java_parser.py."""

    def _run(self, stdout="", stderr="", exit_code=0):
        from releaseguard.parsers.java_parser import parse_java
        return parse_java(_result(Language.JAVA, stdout, stderr, exit_code))

    # --- Maven Surefire ---

    def test_surefire_all_pass(self):
        stdout = textwrap.dedent("""\
            [INFO] -------------------------------------------------------
            [INFO]  T E S T S
            [INFO] -------------------------------------------------------
            [INFO] Running com.example.MyTest
            Tests run: 10, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.123 s - in com.example.MyTest
            [INFO] Results:
            [INFO] Tests run: 10, Failures: 0, Errors: 0, Skipped: 0
            [INFO] BUILD SUCCESS
        """)
        r = self._run(stdout=stdout)
        assert r.total == 10
        assert r.passed == 10
        assert r.failed == 0
        assert r.skipped == 0

    def test_surefire_with_failure(self):
        stdout = textwrap.dedent("""\
            Tests run: 10, Failures: 1, Errors: 0, Skipped: 2 - in com.example.MyTest
        """)
        r = self._run(stdout=stdout, exit_code=1)
        assert r.total == 10
        assert r.failed == 1
        assert r.skipped == 2
        assert r.passed == 7

    def test_surefire_errors_counted_as_failures(self):
        """Maven 'Errors' (crashes) should be treated as failures."""
        stdout = "Tests run: 5, Failures: 0, Errors: 2, Skipped: 0 - in com.example.MyTest\n"
        r = self._run(stdout=stdout, exit_code=1)
        assert r.failed == 2
        assert r.total == 5

    def test_surefire_aggregates_multiple_classes(self):
        stdout = textwrap.dedent("""\
            Tests run: 5, Failures: 0, Errors: 0, Skipped: 0 - in com.example.ATest
            Tests run: 5, Failures: 1, Errors: 0, Skipped: 1 - in com.example.BTest
        """)
        r = self._run(stdout=stdout, exit_code=1)
        assert r.total == 10
        assert r.failed == 1
        assert r.skipped == 1
        assert r.passed == 8

    def test_surefire_failed_tests_section_names(self):
        stdout = textwrap.dedent("""\
            Tests run: 3, Failures: 1, Errors: 0, Skipped: 0 - in com.example.MyTest

            Failed tests:
              com.example.MyTest.testSomething(MyTest.java:42)
        """)
        r = self._run(stdout=stdout, exit_code=1)
        assert r.failures
        assert "testSomething" in r.failures[0].name

    # --- Gradle ---

    def test_gradle_all_pass(self):
        stdout = "10 tests completed\n"
        r = self._run(stdout=stdout)
        assert r.total == 10
        assert r.passed == 10
        assert r.failed == 0

    def test_gradle_with_failure(self):
        stdout = "10 tests completed, 1 failed\n"
        r = self._run(stdout=stdout, exit_code=1)
        assert r.total == 10
        assert r.failed == 1
        assert r.passed == 9

    def test_gradle_with_skipped(self):
        stdout = "10 tests completed, 1 failed, 2 skipped\n"
        r = self._run(stdout=stdout, exit_code=1)
        assert r.total == 10
        assert r.failed == 1
        assert r.skipped == 2
        assert r.passed == 7

    def test_gradle_failure_name_extracted(self):
        stdout = textwrap.dedent("""\
            10 tests completed, 1 failed

            FAILED  com.example.MyTest > testMethod
        """)
        r = self._run(stdout=stdout, exit_code=1)
        assert r.failures
        assert "testMethod" in r.failures[0].name

    # --- Unknown output: no counts fabricated ---

    def test_no_recognisable_output_leaves_counts_none(self):
        r = self._run(stdout="BUILD SUCCESS\n")
        assert r.total is None
        assert r.passed is None


# ===========================================================================
# Collector dispatch
# ===========================================================================

class TestCollectorDispatch:
    """collect_evidence() must call the right parser per language."""

    def _make_result(self, lang: Language, stdout: str, exit_code: int = 0) -> TestRunResult:
        return _result(lang, stdout=stdout, exit_code=exit_code)

    def test_python_dispatched_to_pytest_parser(self):
        from releaseguard.evidence.collector import collect_evidence
        stdout = "========================= 3 passed in 0.10s =========================\n"
        results = collect_evidence([self._make_result(Language.PYTHON, stdout)])
        assert results[0].passed == 3

    def test_node_dispatched_to_node_parser(self):
        from releaseguard.evidence.collector import collect_evidence
        stderr = "ℹ tests 2\nℹ pass 2\nℹ fail 0\n"
        r = _result(Language.NODE, stdout="", stderr=stderr)
        enriched = collect_evidence([r])
        assert enriched[0].total == 2
        assert enriched[0].passed == 2

    def test_rust_dispatched_to_rust_parser(self):
        from releaseguard.evidence.collector import collect_evidence
        stdout = "test result: ok. 4 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out\n"
        results = collect_evidence([self._make_result(Language.RUST, stdout)])
        assert results[0].passed == 4

    def test_go_dispatched_to_go_parser(self):
        from releaseguard.evidence.collector import collect_evidence
        stdout = "--- PASS: TestFoo (0.00s)\nok  example.com/m  0.001s\n"
        results = collect_evidence([self._make_result(Language.GO, stdout)])
        assert results[0].passed == 1

    def test_java_dispatched_to_java_parser(self):
        from releaseguard.evidence.collector import collect_evidence
        stdout = "Tests run: 5, Failures: 0, Errors: 0, Skipped: 0 - in com.example.T\n"
        results = collect_evidence([self._make_result(Language.JAVA, stdout)])
        assert results[0].passed == 5

    def test_unavailable_tooling_skips_parsing(self):
        """Results with unavailable_reason set must not be parsed."""
        from releaseguard.evidence.collector import collect_evidence
        proj = ProjectInfo(language=Language.NODE, confidence=0.9)
        r = TestRunResult(
            project=proj,
            command="npm test",
            exit_code=-1,
            stdout="ℹ tests 2\nℹ pass 2\nℹ fail 0\n",
            stderr="",
            duration_seconds=0.0,
            unavailable_reason="npm not found",
        )
        enriched = collect_evidence([r])
        # Counts must remain None — parser must not have run
        assert enriched[0].total is None
        assert enriched[0].passed is None
