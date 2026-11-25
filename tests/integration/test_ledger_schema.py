"""The ledger rules are enforced by PostgreSQL itself, not only by application code.

Each test goes around the (future) service layer and writes to the database directly,
proving that even buggy or malicious code cannot corrupt the ledger.
"""

from decimal import Decimal

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Account, AccountStatus, AccountType, JournalEntry, JournalEntryType, Posting
from tests.integration.factories import (
    balance_of,
    journal_entry,
    open_account,
    post,
    violated_constraint,
)

pytestmark = pytest.mark.integration

SessionFactory = async_sessionmaker[AsyncSession]


@pytest.fixture
async def settlement(session_factory: SessionFactory) -> Account:
    return await open_account(session_factory, "Settlement", account_type=AccountType.SYSTEM)


@pytest.fixture
async def alice(session_factory: SessionFactory) -> Account:
    return await open_account(session_factory, "Alice")


@pytest.fixture
async def bob(session_factory: SessionFactory) -> Account:
    return await open_account(session_factory, "Bob")


async def deposit(
    session_factory: SessionFactory, settlement: Account, account: Account, amount: str
) -> None:
    await post(
        session_factory,
        journal_entry(
            [(settlement, f"-{amount}"), (account, amount)], entry_type=JournalEntryType.DEPOSIT
        ),
    )


# --------------------------------------------------------------------- happy path


async def test_balanced_entries_post_and_update_balances(
    session_factory: SessionFactory, settlement: Account, alice: Account, bob: Account
) -> None:
    await deposit(session_factory, settlement, alice, "100.00")
    await post(session_factory, journal_entry([(alice, "-30.25"), (bob, "30.25")]))

    assert await balance_of(session_factory, settlement) == Decimal("-100.00")
    assert await balance_of(session_factory, alice) == Decimal("69.75")
    assert await balance_of(session_factory, bob) == Decimal("30.25")


async def test_cached_balances_always_equal_sum_of_postings(
    session_factory: SessionFactory, settlement: Account, alice: Account, bob: Account
) -> None:
    await deposit(session_factory, settlement, alice, "500")
    for amount in ("10", "20.5", "0.01"):
        await post(session_factory, journal_entry([(alice, f"-{amount}"), (bob, amount)]))

    async with session_factory() as session:
        accounts = (await session.scalars(select(Account))).all()
        for account in accounts:
            posted = await session.scalar(
                select(func.coalesce(func.sum(Posting.amount), 0)).where(
                    Posting.account_id == account.id
                )
            )
            assert account.balance == posted
        # Money is conserved: every entry sums to zero, so the whole ledger does too.
        assert await session.scalar(select(func.sum(Posting.amount))) == 0


async def test_amounts_are_exact_decimals(
    session_factory: SessionFactory, settlement: Account, alice: Account
) -> None:
    for _ in range(10):
        await deposit(session_factory, settlement, alice, "0.10")

    balance = await balance_of(session_factory, alice)
    assert isinstance(balance, Decimal)
    assert balance == Decimal("1.00")  # 0.1 added ten times in float is 0.9999999999999999


# ------------------------------------------------------------- balanced entries


async def test_unbalanced_entry_is_rejected_at_commit(
    session_factory: SessionFactory, settlement: Account, alice: Account, bob: Account
) -> None:
    await deposit(session_factory, settlement, alice, "100")

    with pytest.raises(IntegrityError) as exc:
        await post(session_factory, journal_entry([(alice, "-50"), (bob, "40")]))

    assert violated_constraint(exc.value) == "journal_entry_balanced"
    assert await balance_of(session_factory, alice) == Decimal("100")  # rolled back
    assert await balance_of(session_factory, bob) == Decimal("0")


@pytest.mark.parametrize("legs", [0, 1])
async def test_entry_needs_at_least_two_postings(
    session_factory: SessionFactory, alice: Account, legs: int
) -> None:
    entry = journal_entry([(alice, "10")][:legs])

    with pytest.raises(IntegrityError) as exc:
        await post(session_factory, entry)

    assert violated_constraint(exc.value) == "journal_entry_balanced"


async def test_zero_amount_posting_is_rejected(
    session_factory: SessionFactory, alice: Account, bob: Account
) -> None:
    with pytest.raises(IntegrityError) as exc:
        await post(session_factory, journal_entry([(alice, "0"), (bob, "0")]))

    assert violated_constraint(exc.value) == "ck_postings_amount_non_zero"


# ----------------------------------------------------------------- overdrafts


async def test_customer_account_cannot_go_negative(
    session_factory: SessionFactory, settlement: Account, alice: Account, bob: Account
) -> None:
    await deposit(session_factory, settlement, alice, "100")

    with pytest.raises(IntegrityError) as exc:
        await post(session_factory, journal_entry([(alice, "-100.01"), (bob, "100.01")]))

    assert violated_constraint(exc.value) == "ck_accounts_customer_balance_non_negative"
    assert await balance_of(session_factory, alice) == Decimal("100")


async def test_customer_can_spend_entire_balance(
    session_factory: SessionFactory, settlement: Account, alice: Account, bob: Account
) -> None:
    await deposit(session_factory, settlement, alice, "100")

    await post(session_factory, journal_entry([(alice, "-100"), (bob, "100")]))

    assert await balance_of(session_factory, alice) == Decimal("0")


# ------------------------------------------------------------ currency rules


async def test_posting_currency_must_match_account_currency(
    session_factory: SessionFactory, settlement: Account
) -> None:
    euro_account = await open_account(session_factory, "Euro", currency="EUR")

    with pytest.raises(IntegrityError) as exc:
        await post(session_factory, journal_entry([(settlement, "-10"), (euro_account, "10")]))

    assert violated_constraint(exc.value) == "fk_postings_account_id_currency_accounts"


async def test_posting_currency_must_match_entry_currency(
    session_factory: SessionFactory,
) -> None:
    euro_system = await open_account(
        session_factory, "EUR settlement", account_type=AccountType.SYSTEM, currency="EUR"
    )
    euro_customer = await open_account(session_factory, "Euro", currency="EUR")
    entry = journal_entry(
        [(euro_system, "-10"), (euro_customer, "10")], currency="GBP", posting_currency="EUR"
    )

    with pytest.raises(IntegrityError) as exc:
        await post(session_factory, entry)

    assert violated_constraint(exc.value) == "fk_postings_journal_entry_id_currency_journal_entries"


@pytest.mark.parametrize("currency", ["gbp", "GB", "GB1"])
async def test_currency_must_be_iso_4217_code(
    session_factory: SessionFactory, currency: str
) -> None:
    with pytest.raises(IntegrityError) as exc:
        await open_account(session_factory, "Bad", currency=currency)

    assert violated_constraint(exc.value) == "ck_accounts_currency_iso_4217"


# --------------------------------------------------------- append-only ledger


async def test_postings_cannot_be_updated_or_deleted(
    session_factory: SessionFactory, settlement: Account, alice: Account
) -> None:
    await deposit(session_factory, settlement, alice, "100")

    async with session_factory() as session:
        with pytest.raises(IntegrityError) as exc:
            await session.execute(update(Posting).values(amount=Decimal("1000000")))
        assert violated_constraint(exc.value) == "ledger_append_only"

    async with session_factory() as session:
        posting = await session.scalar(select(Posting).limit(1))
        await session.delete(posting)
        with pytest.raises(IntegrityError) as exc:
            await session.commit()
        assert violated_constraint(exc.value) == "ledger_append_only"

    assert await balance_of(session_factory, alice) == Decimal("100")


async def test_journal_entries_cannot_be_updated_or_deleted(
    session_factory: SessionFactory, settlement: Account, alice: Account
) -> None:
    await deposit(session_factory, settlement, alice, "100")

    async with session_factory() as session:
        with pytest.raises(IntegrityError) as exc:
            await session.execute(update(JournalEntry).values(description="tampered"))
        assert violated_constraint(exc.value) == "ledger_append_only"


# ------------------------------------------------------ balance is ledger-only


async def test_balance_cannot_be_set_directly(
    session_factory: SessionFactory, alice: Account
) -> None:
    async with session_factory() as session:
        with pytest.raises(IntegrityError) as exc:
            await session.execute(
                update(Account).where(Account.id == alice.id).values(balance=Decimal("1000000"))
            )
        assert violated_constraint(exc.value) == "balance_managed_by_ledger"


async def test_account_must_open_with_zero_balance(session_factory: SessionFactory) -> None:
    async with session_factory() as session:
        session.add(Account(name="Rich", type=AccountType.CUSTOMER, currency="GBP", balance=50))
        with pytest.raises(IntegrityError) as exc:
            await session.commit()
        assert violated_constraint(exc.value) == "balance_managed_by_ledger"


async def test_other_account_fields_remain_editable(
    session_factory: SessionFactory, alice: Account
) -> None:
    async with session_factory() as session:
        await session.execute(
            update(Account).where(Account.id == alice.id).values(status=AccountStatus.FROZEN)
        )
        await session.commit()

    async with session_factory() as session:
        account = await session.get(Account, alice.id)
        assert account is not None
        assert account.status is AccountStatus.FROZEN
        assert account.updated_at >= account.created_at
