# Benchmark Ground Truth

This file defines the controlled benchmark and should be kept PRIVATE during
the final live demo if the judges should see ReleaseGuard discover the defects
without being told their locations.

## Baseline

All five applications begin in a clean state.

## Planned defect categories

The later benchmark will introduce examples from these categories:

1. Functional requirement failure
2. Missing/weak test coverage
3. Security/configuration problem
4. Dependency problem
5. Documentation mismatch
6. Deployment/health-check problem
7. Environment/configuration mismatch
8. Error-handling problem

## Language coverage

- Python: FastAPI
- Node.js: Express
- Go: net/http
- Java: Spring Boot
- Rust: Axum

## Success criterion

ReleaseGuard must detect problems using evidence appropriate to each project,
rather than using Python-only commands or file assumptions.
