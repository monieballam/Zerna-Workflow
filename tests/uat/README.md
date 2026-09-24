# Zerna User Acceptance Tests (UAT)

End-to-end tests that validate critical user workflows and performance
requirements against a running Zerna instance.

## Prerequisites

- Python 3.11+
- `pytest`, `pytest-asyncio`, `httpx` installed (included in project deps)
- For **local mode**: Docker services running via `docker-compose.integration.yml`
- For **remote mode**: A deployed Zerna staging/production environment

## Environment Setup

### Local Mode (default)

No extra configuration needed. Tests run against the FastAPI app via
ASGI transport with a local PostgreSQL test database.

```bash
# Start backing services
docker compose -f docker-compose.integration.yml up -d

# Run UAT
pytest tests/uat/ -v -m uat
```

### Remote Mode

Set environment variables to target a live deployment:

```bash
export UAT_API_URL=https://api.staging.zerna.io
export UAT_USER_EMAIL=uat-tester@zerna.io
export UAT_USER_PASSWORD=<password>

pytest tests/uat/ -v -m uat
```

## Running Tests

### All UAT tests

```bash
pytest tests/uat/ -v -m uat
```

### Workflow tests only (faster)

```bash
pytest tests/uat/test_uat_workflows.py -v -m uat
```

### Performance tests only (slower)

```bash
pytest tests/uat/test_uat_performance.py -v -m "uat and slow"
```

### Skip slow performance tests

```bash
pytest tests/uat/ -v -m "uat and not slow"
```

## Test Structure

| File                      | Description                                           |
| ------------------------- | ----------------------------------------------------- |
| `conftest.py`             | Shared fixtures: API client, auth, test data, cleanup |
| `test_uat_workflows.py`   | Critical user workflow tests                          |
| `test_uat_performance.py` | Performance SLA verification                          |

## Covered Workflows

1. **Upload Dataset** — Create dataset → verify metadata → paginate
2. **Pipeline Execution** — Create pipeline → create run → check status → list artifacts
3. **Annotation** — Create annotation → edit → approve → list revisions
4. **Export** — Initiate export → check status
5. **Cross-Dataset Analysis** — Select datasets → run pathway analysis → get results
6. **Knowledge Pack** — Upload pack → verify listing → version coexistence

## Performance SLAs

| Metric                      | Target                    |
| --------------------------- | ------------------------- |
| API p50 latency             | < 100ms                   |
| API p99 latency             | < 500ms                   |
| 100 concurrent requests     | All succeed within 1s p99 |
| 1M cell metadata operations | < 1s                      |

## Collecting and Reporting Feedback

After running UAT, generate a JUnit XML report for CI integration:

```bash
pytest tests/uat/ -v -m uat --junitxml=reports/uat-results.xml
```

For human-readable output with timing details:

```bash
pytest tests/uat/ -v -m uat --tb=short --durations=20
```

Share the report with stakeholders and log any failures as issues
with the `uat-feedback` label.
