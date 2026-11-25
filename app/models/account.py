import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models._types import created_at, currency_check, currency_code, str_enum, uuid_pk


class AccountType(enum.StrEnum):
    CUSTOMER = "customer"  # balance may never go below zero
    SYSTEM = "system"  # internal accounts, e.g. external settlement; may go negative


class AccountStatus(enum.StrEnum):
    ACTIVE = "active"
    FROZEN = "frozen"
    CLOSED = "closed"


class Account(Base):
    """A ledger account holding a single currency.

    `balance` is a cached running total of the account's postings. It is maintained
    exclusively by a database trigger when postings are inserted and cannot be written
    directly, so it can never drift from the ledger.
    """

    __tablename__ = "accounts"
    __table_args__ = (
        currency_check(),
        CheckConstraint("type = 'system' OR balance >= 0", name="customer_balance_non_negative"),
        # Target of the composite FK from postings: guarantees posting currency
        # always equals the account's currency.
        UniqueConstraint("id", "currency"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(100))
    type: Mapped[AccountType] = mapped_column(str_enum(AccountType, "account_type"))
    status: Mapped[AccountStatus] = mapped_column(
        str_enum(AccountStatus, "account_status"),
        default=AccountStatus.ACTIVE,
        server_default=AccountStatus.ACTIVE.value,
    )
    currency: Mapped[str] = currency_code()
    balance: Mapped[Decimal] = mapped_column(default=Decimal(0), server_default="0")
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
