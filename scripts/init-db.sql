-- Zerna Platform - Database Initialization Script
-- This script runs automatically when PostgreSQL container starts for the first time.
--
-- Schema (enums, tables, indexes) is owned by Alembic: run
--   uv run --directory apps/api alembic upgrade head
-- after the stack is up. Do not duplicate DDL here or migrations will fail.

-- Create extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- For full-text search

-- Create Temporal database (if not exists)
-- Temporal will create its own schema, but we need the database
SELECT 'CREATE DATABASE temporal'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'temporal')\gexec

-- Connect to main application database
\c zerna;

CREATE SCHEMA IF NOT EXISTS public;

GRANT ALL PRIVILEGES ON SCHEMA public TO zerna;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO zerna;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO zerna;

ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO zerna;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO zerna;

DO $$
BEGIN
    RAISE NOTICE 'Zerna database initialized (extensions + temporal DB). Apply Alembic migrations for application schema.';
END $$;
