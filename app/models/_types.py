"""Column helpers shared by models."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import CHAR, CheckConstraint, Enum, func
from sqlalchemy.orm import Mapped, mapped_column


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )


def created_at() -> Mapped[datetime]:
    return mapped_column(server_default=func.now())


def currency_code() -> Mapped[str]:
    """ISO 4217 alphabetic code, e.g. GBP."""
    return mapped_column(CHAR(3))


def currency_check() -> CheckConstraint:
    return CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso_4217")


def str_enum(enum_cls: type[enum.StrEnum], name: str) -> Enum:
    """Store enums as VARCHAR + CHECK constraint (not a native PG enum).

    Native enums need special ALTER TYPE migrations to evolve; a check constraint is
    just dropped and recreated.
    """
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=max(len(member.value) for member in enum_cls),
        values_callable=lambda cls: [member.value for member in cls],
    )
