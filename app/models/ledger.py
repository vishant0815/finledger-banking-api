"""Double-entry ledger: journal entries and their postings.

Sign convention: a posting's `amount` is signed. Positive increases the account's
balance, negative decreases it. Every journal entry's postings sum to exactly zero,
so money is only ever moved, never created or destroyed. Deposits and withdrawals
balance against a SYSTEM settlement account.
"""

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models._types import created_at, currency_check, currency_code, str_enum, uuid_pk


class JournalEntryType(enum.StrEnum):
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    TRANSFER = "transfer"
    REVERSAL = "reversal"


class JournalEntry(Base):
    """One atomic financial event. Append-only: corrections are new REVERSAL entries."""

    __tablename__ = "journal_entries"
    __table_args__ = (
        currency_check(),
        UniqueConstraint("id", "currency"),  # target of postings' composite FK
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    entry_type: Mapped[JournalEntryType] = mapped_column(
        str_enum(JournalEntryType, "journal_entry_type")
    )
    currency: Mapped[str] = currency_code()
    description: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = created_at()

    # lazy="raise": never trigger implicit I/O in async code; load explicitly.
    postings: Mapped[list["Posting"]] = relationship(
        back_populates="journal_entry",
        lazy="raise",
        foreign_keys="Posting.journal_entry_id",
        primaryjoin="JournalEntry.id == Posting.journal_entry_id",
    )


class Posting(Base):
    """One leg of a journal entry against one account. Append-only."""

    __tablename__ = "postings"
    __table_args__ = (
        CheckConstraint("amount <> 0", name="amount_non_zero"),
        # Composite FKs make currency mismatches impossible at the database level:
        # posting currency == account currency == journal entry currency.
        ForeignKeyConstraint(["account_id", "currency"], ["accounts.id", "accounts.currency"]),
        ForeignKeyConstraint(
            ["journal_entry_id", "currency"],
            ["journal_entries.id", "journal_entries.currency"],
        ),
        Index(None, "account_id", "created_at"),  # account statements
        Index(None, "journal_entry_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    journal_entry_id: Mapped[uuid.UUID]
    account_id: Mapped[uuid.UUID]
    currency: Mapped[str] = currency_code()
    amount: Mapped[Decimal]
    created_at: Mapped[datetime] = created_at()

    journal_entry: Mapped[JournalEntry] = relationship(
        back_populates="postings",
        lazy="raise",
        foreign_keys="Posting.journal_entry_id",
        primaryjoin="JournalEntry.id == Posting.journal_entry_id",
    )
