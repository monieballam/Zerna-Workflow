"""Tests for Alembic database migrations.

These tests verify that migrations can be applied and rolled back successfully.
They are designed to run in CI to catch migration issues early.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

# These tests require a real PostgreSQL database; skip when only SQLite is available.
_db_url = os.getenv("DATABASE_URL", "")
_requires_postgres = pytest.mark.skipif(
    "postgresql" not in _db_url,
    reason="Migration tests require a PostgreSQL database (set DATABASE_URL)",
)

pytestmark = _requires_postgres


@pytest.fixture
def database_url():
    """Get database URL from environment or use default test database."""
    return os.getenv("DATABASE_URL", "postgresql://zerna:zerna@localhost:5432/zerna")


@pytest.fixture
def alembic_config_path():
    """Get path to alembic.ini file."""
    api_dir = Path(__file__).parent.parent
    return api_dir / "alembic.ini"


@pytest.fixture
def engine(database_url):
    """Create SQLAlchemy engine for testing."""
    return create_engine(database_url)


@pytest.fixture(autouse=True)
def setup_python_path():
    """Add workspace root to Python path for imports."""
    workspace_root = Path(__file__).parent.parent.parent.parent
    sys.path.insert(0, str(workspace_root))
    yield
    sys.path.remove(str(workspace_root))


def run_alembic_command(command: list[str], cwd: Path, env: dict) -> subprocess.CompletedProcess:
    """Run an Alembic command and return the result."""
    return subprocess.run(
        ["alembic"] + command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )


class TestMigrations:
    """Test suite for database migrations."""

    def test_migrations_can_upgrade_to_head(self, database_url, alembic_config_path, engine):
        """Test that migrations can be applied from scratch to head."""
        # Drop all tables to start fresh
        with engine.connect() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
            conn.commit()

        # Run migrations
        api_dir = alembic_config_path.parent
        env = os.environ.copy()
        env["DATABASE_URL"] = database_url

        result = run_alembic_command(["upgrade", "head"], api_dir, env)
        assert result.returncode == 0, f"Migration failed: {result.stderr}"

        # Verify tables were created
        inspector = inspect(engine)
        tables = inspector.get_table_names()

        expected_tables = {
            "alembic_version",
            "organizations",
            "users",
            "organization_users",
            "datasets",
            "dataset_versions",
            "pipeline_templates",
            "runs",
            "artifacts",
            "annotation_revisions",
            "knowledge_packs",
            "feedback",
            "audit_events",
        }

        assert set(tables) == expected_tables, f"Missing tables: {expected_tables - set(tables)}"

    def test_migrations_can_downgrade_to_base(self, database_url, alembic_config_path, engine):
        """Test that migrations can be rolled back to base."""
        # First ensure we're at head
        api_dir = alembic_config_path.parent
        env = os.environ.copy()
        env["DATABASE_URL"] = database_url

        # Drop and recreate schema to start fresh
        with engine.connect() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
            conn.commit()

        # Upgrade to head first
        run_alembic_command(["upgrade", "head"], api_dir, env)

        # Then downgrade to base
        result = run_alembic_command(["downgrade", "base"], api_dir, env)
        assert result.returncode == 0, f"Downgrade failed: {result.stderr}"

        # Verify all tables except alembic_version were dropped
        inspector = inspect(engine)
        tables = inspector.get_table_names()

        # Only alembic_version should remain
        assert tables == ["alembic_version"], f"Tables not cleaned up: {tables}"
