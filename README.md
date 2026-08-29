# ReleaseGuard Polyglot Benchmark

A controlled multi-language benchmark repository for the **ReleaseGuard** release-readiness analysis tool.

ReleaseGuard scans a repository, detects every language/framework present, runs each project's test suite, parses the results, and produces a structured release-readiness report with findings and a final **READY / REVIEW_REQUIRED / BLOCKED** decision.

---

## Supported languages

| Language | Framework | Test runner | Test command |
|----------|-----------|-------------|--------------|
| Python   | FastAPI   | pytest      | `python -m pytest -v` |
| Node.js  | Express   | npm test    | `npm test` |
| Go       | net/http  | go test     | `go test -json ./...` |
| Java     | Spring Boot | Maven / Gradle | `mvn test` / `gradle test` |
| Rust     | Axum      | cargo test  | `cargo test` |

---

## Repository layout

```text
releaseguard-polyglot-benchmark/
├── python-app/          # FastAPI Task Manager
├── node-app/            # Express Task Manager
├── go-app/              # Go net/http Task Manager
├── java-app/            # Spring Boot Task Manager
├── rust-app/            # Rust Axum Task Manager
├── releaseguard/        # ReleaseGuard core package
│   ├── scanner/         # Language detection & command resolution
│   ├── runners/         # Test execution engine
│   ├── parsers/         # Per-language output parsers
│   ├── analyzer/        # Rule engine & findings
│   ├── evidence/        # Evidence collection & linking
│   ├── models/          # Core data models
│   └── web/             # Web UI
├── tests/               # Full test suite (416+ tests)
├── benchmark/           # Benchmark scenarios
├── scripts/             # Helper scripts
├── demo/                # Demo projects (passing / failing / config issues)
└── .github/workflows/   # CI pipelines
```

---

## Quick start

```bash
# Install ReleaseGuard
pip install -e .

# Run against any local repository
releaseguard scan ./go-app

# Run the full test suite
python -m pytest tests/ -v
```

---

## How ReleaseGuard works

1. **Detect** — scans the repository for `go.mod`, `package.json`, `Cargo.toml`, `pom.xml`, `pyproject.toml`, etc.
2. **Command resolution** — picks the appropriate test command for each detected project.
3. **Execute** — runs each project's test suite in its own working directory.
4. **Parse** — interprets the raw output using a language-specific parser.
5. **Analyze** — applies deterministic safety rules to produce findings.
6. **Decide** — aggregates findings into a final release-readiness decision.

### Go test parsing

Go tests are executed with `go test -json ./...`. The JSON event stream is parsed line-by-line to extract exact pass / fail / skip counts and individual failure details. A project where all tests pass will reach **READY**. The safety rule that raises a HIGH "test execution cannot be verified" finding only fires when `total` remains `None` after parsing (e.g. non-JSON, non-verbose output with no recognisable events).

---

## Safety rules (analyzer)

| Rule | Severity | Fires when |
|------|----------|------------|
| Tooling unavailable | HIGH | Test executable not found on PATH |
| Execution error | HIGH | Runner started but could not complete |
| Tests failed | HIGH | One or more test cases failed |
| No tests found | HIGH | `total == 0` |
| Unverified execution | HIGH | `exit_code == 0` but `total` is `None` |
| Authorization failures | MEDIUM–HIGH | Auth-related test failures |
| Validation failures | MEDIUM | Input-validation test failures |
| State corruption | MEDIUM | State-transition test failures |

---

## Demo scenarios

The `demo/` directory contains three intentionally broken Python projects used to validate ReleaseGuard's detection capabilities:

| Demo | Issue type |
|------|------------|
| `failing-test-demo` | Tests that fail at runtime |
| `dependency-issue-demo` | Missing Python dependency |
| `config-issue-demo` | Missing environment variable |

---

## Contributing

1. Keep the `main` branch as the clean baseline.
2. Add benchmark defects in separate branches or the `benchmark/` directory.
3. All changes must pass `python -m pytest tests/ -v` before merging.
