import asyncio
from collections.abc import Callable

import pytest
from alembic import command
from sqlalchemy import inspect
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.conftest import alembic_config, run_in_thread

pytestmark = pytest.mark.integration

LEDGER_TABLES = {"accounts", "journal_entries", "postings"}


async def _table_names(url: URL) -> set[str]:
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        names = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())
    await engine.dispose()
    return set(names)


def test_models_and_migrations_are_in_sync(create_test_database: Callable[[str], URL]) -> None:
    config = alembic_config(create_test_database("test_migrations_check"))
    run_in_thread(command.upgrade, config, "head")

    # Fails if a model was changed without generating a migration.
    run_in_thread(command.check, config)


def test_full_downgrade_and_upgrade_round_trip(
    create_test_database: Callable[[str], URL],
) -> None:
    url = create_test_database("test_migrations_round_trip")
    config = alembic_config(url)

    run_in_thread(command.upgrade, config, "head")
    assert run_in_thread(asyncio.run, _table_names(url)) >= LEDGER_TABLES

    run_in_thread(command.downgrade, config, "base")
    assert run_in_thread(asyncio.run, _table_names(url)) == {"alembic_version"}

    run_in_thread(command.upgrade, config, "head")
    assert run_in_thread(asyncio.run, _table_names(url)) >= LEDGER_TABLES
