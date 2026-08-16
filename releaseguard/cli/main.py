"""Main CLI entry point for ReleaseGuard.

Usage:
    releaseguard scan <repository-path-or-github-url>
"""

from __future__ import annotations

import sys
from pathlib import Path

from releaseguard.analyzer.rules import analyze
from releaseguard.cli.renderer import render_report
from releaseguard.evidence.collector import collect_evidence
from releaseguard.models.core import RepositoryReport
from releaseguard.policy.policy import decide
from releaseguard.repository.loader import RepositoryLoadError, load_repository
from releaseguard.runners.runner import run_tests
from releaseguard.scanner.commands import detect_test_command
from releaseguard.scanner.detector import detect_projects


def main() -> None:
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help"):
        _print_help()
        sys.exit(0)

    if args[0] == "scan":
        if len(args) < 2:
            print("Error: 'scan' requires a repository path or GitHub URL.", file=sys.stderr)
            print(
                "Usage: releaseguard scan <repository-path-or-github-url>",
                file=sys.stderr,
            )
            sys.exit(1)

        target = args[1]

        try:
            with load_repository(target) as repo_path:
                _cmd_scan(repo_path)
        except RepositoryLoadError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)

    else:
        print(f"Error: unknown command '{args[0]}'.", file=sys.stderr)
        _print_help()
        sys.exit(1)


def _cmd_scan(repo_path: Path) -> None:
    """Execute the scan pipeline and print the report."""

    # 1. Detect languages / projects
    projects = detect_projects(repo_path)

    # 2. Detect test commands for each project
    for proj in projects:
        detect_test_command(proj, repo_path)

    # 3. Execute tests
    raw_runs = [run_tests(proj, repo_path) for proj in projects]

    # 4. Parse / enrich evidence
    runs = collect_evidence(raw_runs)

    # 5. Analyze for risk findings
    findings = analyze(runs, repo_path=repo_path)

    # 6. Release decision
    decision = decide(findings)

    # 7. Build report
    report = RepositoryReport(
        repository_path=str(repo_path),
        projects=projects,
        test_runs=runs,
        findings=findings,
        decision=decision,
    )

    # 8. Render and print
    print(render_report(report))


def _print_help() -> None:
    print("ReleaseGuard — release-readiness analysis tool")
    print("")
    print("Usage:")
    print("  releaseguard scan <repository-path-or-github-url>")
    print("")
    print("Commands:")
    print(
        "  scan    Analyze a local repository or public GitHub repository "
        "and produce a release-readiness assessment"
    )


if __name__ == "__main__":
    main()