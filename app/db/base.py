"""Declarative base shared by all ORM models."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, MetaData, Numeric
from sqlalchemy.orm import DeclarativeBase

# Deterministic constraint/index names, so Alembic migrations are stable and
# database errors can be mapped back to the rule that was violated.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# Money: exact fixed-point decimal, never float. 19 digits with 4 decimal places
# covers minor units for every ISO 4217 currency with headroom.
MONEY = Numeric(19, 4)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {  # noqa: RUF012 - SQLAlchemy's documented pattern
        datetime: DateTime(timezone=True),
        Decimal: MONEY,
    }
