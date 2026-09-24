# Temporal Quick Start

## 🚀 Get Started in 3 Steps

### 1. Start Services

```bash
./scripts/setup-dev-env.sh
```

This starts PostgreSQL, Redis, Temporal, MinIO, observability services, and the supervised `worker` service.

### 2. Follow Worker Logs

```bash
./scripts/start-worker.sh
```

To run the worker directly from your checkout without Docker supervision:

```bash
./scripts/start-worker.sh --local
```

### 3. View UI

Open:

- Temporal UI: http://localhost:8080
- Grafana: http://localhost:3001
- Jaeger: http://localhost:16686

---

## 📋 Common Commands

### Check Status

```bash
# Verify setup
./scripts/test-temporal-setup.sh

# Check Temporal health
docker compose exec temporal tctl cluster health

# View worker logs
docker compose logs -f worker
```

### Run Tests

```bash
# Connection test
python workflows/tests/test_worker_connection.py

# All tests
pytest workflows/tests/ -v
```

### Debugging

```bash
# View Temporal logs
docker compose logs temporal -f

# View all service logs
docker compose logs -f

# Restart Temporal
docker compose restart temporal
```

---

## 🔧 Configuration

Key environment variables in `.env`:

```bash
TEMPORAL_ADDRESS=localhost:7233
TEMPORAL_NAMESPACE=default
TEMPORAL_TASK_QUEUE=zerna-control-plane
```

---

## 📚 Documentation

- **Setup Guide**: [TEMPORAL_SETUP.md](./TEMPORAL_SETUP.md)
- **Usage Guide**: [README.md](./README.md)
- **Implementation**: [IMPLEMENTATION_SUMMARY.md](./IMPLEMENTATION_SUMMARY.md)

---

## 🐛 Troubleshooting

| Problem              | Solution                                                                                                    |
| -------------------- | ----------------------------------------------------------------------------------------------------------- |
| Worker won't connect | `docker compose up -d temporal worker`                                                                      |
| Activities timeout   | Check worker logs and the API stale-run reconciler settings                                                 |
| Workflows stuck      | Check `docker compose ps worker`, `docker compose logs worker`, and `GET /v1/runs/{id}` progress timestamps |
| Import errors        | `uv sync` to install dependencies                                                                           |

---

## 🎯 Next Steps

1. Start the API with `./scripts/start-api.sh`
2. Start the web app with `pnpm --dir apps/web dev`
3. Create a dataset upload, then start a run
4. Use Temporal UI and Grafana to monitor worker behavior
