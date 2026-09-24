#!/usr/bin/env bash
# Zerna Platform - Redis Initialization Script
# This script configures Redis with initial settings

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

COMPOSE_BIN=(docker compose)

REDIS_HOST=${REDIS_HOST:-localhost}
REDIS_PORT=${REDIS_PORT:-6379}
REDIS_PASSWORD=${REDIS_PASSWORD:-zerna_redis_password}

echo "Initializing Redis configuration..."

# Connect to Redis and set initial configuration
"${COMPOSE_BIN[@]}" exec -T redis redis-cli -a "$REDIS_PASSWORD" <<EOF
# Set memory policy for cache eviction
CONFIG SET maxmemory-policy allkeys-lru

# Set max memory (1GB for development)
CONFIG SET maxmemory 1gb

# Enable keyspace notifications for cache invalidation
CONFIG SET notify-keyspace-events Ex

# Save configuration
CONFIG REWRITE

# Test connection
PING
EOF

echo "Redis initialized successfully!"
echo ""
echo "Redis configuration:"
echo "  Memory policy: allkeys-lru"
echo "  Max memory: 1GB"
echo "  Keyspace notifications: Enabled"
