"""Small helpers for building ledger data in integration tests."""

from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Account, AccountType, JournalEntry, JournalEntryType, Posting

SessionFactory = async_sessionmaker[AsyncSession]


async def open_account(
    session_factory: SessionFactory,
    name: str,
    *,
    account_type: AccountType = AccountType.CUSTOMER,
    currency: str = "GBP",
) -> Account:
    async with session_factory() as session:
        account = Account(name=name, type=account_type, currency=currency)
        session.add(account)
        await session.commit()
        return account


def journal_entry(
    legs: Sequence[tuple[Account, str]],
    *,
    entry_type: JournalEntryType = JournalEntryType.TRANSFER,
    currency: str = "GBP",
    posting_currency: str | None = None,
) -> JournalEntry:
    """Build an entry from (account, amount) legs. Amounts are strings: never floats."""
    entry = JournalEntry(entry_type=entry_type, currency=currency)
    entry.postings = [
        Posting(
            account_id=account.id, currency=posting_currency or currency, amount=Decimal(amount)
        )
        for account, amount in legs
    ]
    return entry


async def post(session_factory: SessionFactory, entry: JournalEntry) -> None:
    async with session_factory() as session:
        session.add(entry)
        await session.commit()


async def balance_of(session_factory: SessionFactory, account: Account) -> Decimal:
    async with session_factory() as session:
        balance = await session.scalar(select(Account.balance).where(Account.id == account.id))
        assert balance is not None
        return balance
