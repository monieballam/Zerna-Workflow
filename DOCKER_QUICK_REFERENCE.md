# Docker Quick Reference

## Start

### Core stack

```bash
./scripts/setup-dev-env.sh
```

### Core stack plus observability

```bash
./scripts/setup-dev-env.sh --with-observability
```

### Raw compose

```bash
docker compose up -d
docker compose --profile observability up -d
```

## Stop

```bash
docker compose down
./scripts/teardown-dev-env.sh --remove-volumes
```

## Logs

```bash
docker compose logs -f
docker compose logs -f postgres
docker compose logs -f temporal
docker compose logs -f worker
./scripts/start-worker.sh
```

## Status

```bash
docker compose ps
docker compose config --services
```

## Shell Access

```bash
docker compose exec postgres psql -U zerna -d zerna
docker compose exec redis redis-cli -a zerna_redis_password
docker compose exec minio ls /data
```

## URLs

### Core stack

- PostgreSQL: `localhost:5432`
- Redis: `localhost:6379`
- Temporal UI: `http://localhost:8080`
- MinIO API: `http://localhost:19000`
- MinIO Console: `http://localhost:19001`

### Observability profile only

- Jaeger UI: `http://localhost:16686`
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3001`

## Reset

```bash
docker compose down -v
rm -f .env
cp .env.example .env
./scripts/setup-dev-env.sh
```

## Validation

```bash
./scripts/test-temporal-setup.sh
docker stats
```
