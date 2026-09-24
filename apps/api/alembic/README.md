# Alembic Database Migrations

This directory contains Alembic database migrations for the Zerna Control Plane API.

## Overview

Alembic is used to manage database schema changes in a version-controlled manner. Migrations are automatically generated from SQLAlchemy model changes and can be applied or rolled back as needed.

## Prerequisites

- PostgreSQL database running (see `docker-compose.yml` in project root)
- `DATABASE_URL` environment variable set (or use default from `.env`)

## Common Commands

### Generate a New Migration

After modifying SQLAlchemy models in `apps/api/models/`, generate a migration:

```bash
cd apps/api
export DATABASE_URL="postgresql://zerna:zerna@localhost:5432/zerna"
alembic revision --autogenerate -m "description_of_changes"
```

**Important**: Always review the generated migration file before applying it. Alembic's autogenerate is smart but not perfect.

### Apply Migrations

Apply all pending migrations to the database:

```bash
cd apps/api
export DATABASE_URL="postgresql://zerna:zerna@localhost:5432/zerna"
alembic upgrade head
```

Apply migrations up to a specific revision:

```bash
alembic upgrade <revision_id>
```

### Rollback Migrations

Rollback the last migration:

```bash
alembic downgrade -1
```

Rollback all migrations:

```bash
alembic downgrade base
```

Rollback to a specific revision:

```bash
alembic downgrade <revision_id>
```

### View Migration History

Show current database version:

```bash
alembic current
```

Show migration history:

```bash
alembic history
```

Show pending migrations:

```bash
alembic history --verbose
```

## Migration File Naming

Migration files are automatically named with the format:

```
YYYYMMDD_HHMM_<revision_id>_<description>.py
```

Example: `20260312_1432_e1acfd25f882_initial_schema.py`

## Configuration

### Database URL

The database URL is read from the `DATABASE_URL` environment variable. If not set, Alembic will use the value in `alembic.ini` (which is commented out by default).

### Environment Variables

- `DATABASE_URL`: PostgreSQL connection string (required)
  - Format: `postgresql://user:password@host:port/database`
  - Example: `postgresql://zerna:zerna@localhost:5432/zerna`

### Autogenerate Settings

The `env.py` file is configured to:

- Import all models from `apps.api.models`
- Compare types and server defaults
- Detect table, column, index, and constraint changes
- Support both PostgreSQL (JSONB) and SQLite (JSON) for testing

## Testing Migrations

Run migration tests to verify migrations work correctly:

```bash
cd apps/api
pytest tests/test_migrations.py -v
```

Tests verify:

- Migrations can upgrade from scratch to head
- Migrations can downgrade to base
- Migrations are idempotent (can run multiple times safely)
- All models have corresponding migrations
- Foreign keys, indexes, and unique constraints are created

## CI/CD Integration

Migrations are tested in CI on every pull request. The test suite:

1. Creates a fresh test database
2. Applies all migrations
3. Verifies schema matches models
4. Tests rollback functionality
5. Cleans up test database

## Best Practices

### Before Creating a Migration

1. Ensure your SQLAlchemy models are correct
2. Run existing tests to verify models work
3. Review the design document to ensure schema matches requirements

### After Generating a Migration

1. **Review the generated migration file carefully**
2. Check for:
   - Correct table and column names
   - Proper data types (especially JSONB vs JSON)
   - Foreign key constraints with correct `ondelete` behavior
   - Indexes on frequently queried columns
   - Unique constraints where needed
3. Test the migration locally:
   ```bash
   alembic upgrade head
   alembic downgrade -1
   alembic upgrade head
   ```
4. Run the test suite:
   ```bash
   pytest tests/test_migrations.py
   ```

### Migration Guidelines

- **One logical change per migration**: Don't mix unrelated schema changes
- **Always provide downgrade**: Ensure `downgrade()` properly reverses `upgrade()`
- **Test data migrations**: If migrating data, test with realistic data volumes
- **Avoid breaking changes**: Consider backward compatibility for zero-downtime deployments
- **Document complex migrations**: Add comments explaining non-obvious changes

### Handling Data Migrations

For migrations that transform data (not just schema):

1. Create a separate migration file
2. Use `op.execute()` for SQL statements
3. Consider batch processing for large tables
4. Test with production-like data volumes
5. Have a rollback plan

Example:

```python
def upgrade():
    # Schema change
    op.add_column('users', sa.Column('full_name', sa.String(255)))

    # Data migration
    op.execute("""
        UPDATE users
        SET full_name = first_name || ' ' || last_name
        WHERE full_name IS NULL
    """)

    # Make column non-nullable after data migration
    op.alter_column('users', 'full_name', nullable=False)
```

## Troubleshooting

### "Can't locate revision identified by 'xxx'"

The database has a migration reference that doesn't exist in the `versions/` directory. This can happen if:

- The database was migrated with old code
- Migration files were deleted
- Working with a different branch

**Solution**: Reset the database or manually update `alembic_version` table.

### "Target database is not up to date"

The database schema doesn't match the current migration state.

**Solution**: Run `alembic upgrade head` to apply pending migrations.

### Autogenerate Doesn't Detect Changes

Alembic's autogenerate has limitations. It may not detect:

- Changes to table or column comments
- Changes to server defaults (sometimes)
- Renamed tables or columns (appears as drop + create)

**Solution**: Manually edit the migration file or use `alembic revision` (without `--autogenerate`) to create a manual migration.

### Connection Errors

If you get connection errors:

1. Verify PostgreSQL is running: `docker ps | grep postgres`
2. Check `DATABASE_URL` is correct
3. Verify credentials match `docker-compose.yml`
4. Test connection: `psql $DATABASE_URL -c "SELECT 1"`

## Production Deployment

### Pre-Deployment Checklist

- [ ] All migrations tested locally
- [ ] Migration tests pass in CI
- [ ] Downgrade path tested
- [ ] Database backup created
- [ ] Deployment plan documented
- [ ] Rollback plan documented

### Deployment Steps

1. **Backup database**:

   ```bash
   pg_dump $DATABASE_URL > backup_$(date +%Y%m%d_%H%M%S).sql
   ```

2. **Apply migrations**:

   ```bash
   alembic upgrade head
   ```

3. **Verify application**:
   - Check application logs
   - Run smoke tests
   - Monitor error rates

4. **Rollback if needed**:
   ```bash
   alembic downgrade -1
   # Restore from backup if necessary
   psql $DATABASE_URL < backup_YYYYMMDD_HHMMSS.sql
   ```

## Additional Resources

- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
