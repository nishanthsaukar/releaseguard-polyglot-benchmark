# ReleaseGuard Polyglot Benchmark MVP

A controlled multi-language benchmark repository for the ReleaseGuard project.

Supported sample applications:

- Python / FastAPI
- Node.js / Express
- Go / net/http
- Java / Spring Boot
- Rust / Axum

Each application exposes a small Task Manager API with a health endpoint.
The repository is intentionally kept clean in this baseline version.

## Repository layout

```text
release-readiness-polyglot-mvp/
├── python-app/
├── node-app/
├── go-app/
├── java-app/
├── rust-app/
├── benchmark/
├── scripts/
└── .github/workflows/
```

## Run the language-specific apps

See the README in each directory.

## Baseline rule

This is the CLEAN baseline.

Do not introduce benchmark defects until the clean applications have been
tested and tagged as the baseline. A later benchmark phase will add controlled
release-readiness problems independently to each language.

## What ReleaseGuard should eventually do

ReleaseGuard should inspect a repository, identify its language/framework,
run appropriate checks, gather evidence, report blockers, and re-verify after
remediation.

It should NOT assume that the repository is Python.
