# Migrations

Pipelit uses [Alembic](https://alembic.sqlalchemy.org/) for database schema migrations. This guide covers best practices for creating and managing migrations safely.

## Before You Start

Before creating any migration, always check the current state:

```bash
cd platform
source ../.venv/bin/activate

# Check for multiple heads (conflicting migrations)
alembic heads

# Show current database version
alembic current

# Show recent migration history
alembic history --verbose -n 5
```

!!! danger "Always check for conflicting heads"
    Multiple heads indicate that two migrations were created in parallel without merging. You **must** resolve this before creating a new migration. Creating a migration on top of conflicting heads will make the situation worse.

### Resolving Conflicting Heads

If `alembic heads` shows more than one head:

```bash
# Create a merge migration
alembic merge heads -m "merge conflicting heads"

# Apply it
alembic upgrade head
```

## Creating a Migration

After modifying SQLAlchemy models in `platform/models/`:

```bash
# 1. Verify only one head exists
alembic heads

# 2. Auto-generate the migration
alembic revision --autogenerate -m "describe your change"

# 3. Review the generated file in platform/alembic/versions/
#    ALWAYS review auto-generated migrations before applying

# 4. Apply the migration
alembic upgrade head
```

### Reviewing Auto-generated Migrations

Alembic's `--autogenerate` compares your SQLAlchemy models against the database and generates upgrade/downgrade functions. Always review the generated file because auto-generation can:

- Miss some changes (e.g., renaming columns looks like drop + add)
- Generate incorrect operations for complex changes
- Include unintended changes from model imports

Look for the generated file in `platform/alembic/versions/` and verify that the `upgrade()` and `downgrade()` functions match your intentions.

## SQLite Considerations

Pipelit uses SQLite by default. SQLite has significant limitations for schema migrations:

!!! warning "batch_alter_table is dangerous with SQLite"
    SQLite does not support most `ALTER TABLE` operations natively. Alembic works around this with `batch_alter_table`, which:

    1. Creates a new temporary table with the desired schema
    2. Copies all data from the old table
    3. Drops the old table
    4. Renames the new table

    This process can **cascade and delete data** if foreign key constraints are involved. Test thoroughly.

### Safe Practices for SQLite Migrations

- **Test against existing data**, not just empty databases
- **Back up your database** before running migrations: `cp db.sqlite3 db.sqlite3.backup`
- **Avoid dropping columns** if possible -- add new columns instead
- **Be careful with foreign key changes** -- these trigger full table rebuilds
- **Test the downgrade path** as well as the upgrade path

### Example: Safe Column Addition

Adding a nullable column is the safest migration for SQLite:

```python
def upgrade():
    op.add_column("workflow_nodes", sa.Column("new_field", sa.String(255), nullable=True))


def downgrade():
    # For SQLite, dropping columns requires batch_alter_table
    with op.batch_alter_table("workflow_nodes") as batch_op:
        batch_op.drop_column("new_field")
```

### Example: Avoiding Data Loss

When a migration involves `batch_alter_table`, explicitly verify that data survives:

```python
def upgrade():
    # Use batch_alter_table for SQLite compatibility
    with op.batch_alter_table("component_configs") as batch_op:
        batch_op.add_column(sa.Column("new_setting", sa.String(100), nullable=True))
        # Do NOT drop existing columns in the same batch unless absolutely necessary
```

## Common Migration Commands

```bash
# Apply all pending migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1

# Rollback to a specific revision
alembic downgrade abc123

# Show current version
alembic current

# Show migration history
alembic history --verbose

# Show pending migrations
alembic upgrade head --sql  # Preview SQL without executing

# Create an empty migration (for manual SQL)
alembic revision -m "manual migration description"
```

## Testing Migrations

### Against an Empty Database

```bash
# Remove the database and re-run all migrations
rm platform/db.sqlite3
cd platform
alembic upgrade head
```

### Against Existing Data

```bash
# Back up your database
cp platform/db.sqlite3 platform/db.sqlite3.backup

# Run the migration
cd platform
alembic upgrade head

# Verify the application works
uvicorn main:app --host 0.0.0.0 --port 8000

# If something went wrong, restore
cp platform/db.sqlite3.backup platform/db.sqlite3
```

### In the Test Suite

The test suite uses an in-memory SQLite database and calls `Base.metadata.create_all()` directly (bypassing Alembic). This means test passes do not guarantee migration correctness. Always test migrations manually against a real database with existing data.

## Migration Tips

1. **One migration per logical change.** Do not combine unrelated schema changes in a single migration.

2. **Write descriptive messages.** Use `-m "add token_count column to execution_logs"` not `-m "update models"`.

3. **Make migrations reversible.** Always implement both `upgrade()` and `downgrade()` functions.

4. **Avoid data migrations in schema migrations.** If you need to transform existing data, create a separate data migration after the schema migration.

5. **Coordinate with team members.** If multiple people are working on migrations simultaneously, communicate to avoid conflicting heads.
