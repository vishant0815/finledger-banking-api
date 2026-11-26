"""Helpers for interpreting database errors."""


def violated_constraint(exc: BaseException) -> str | None:
    """Return the name of the constraint behind a database error, if any.

    Walks SQLAlchemy -> DBAPI adapter -> asyncpg exceptions. Works for real
    constraints and for the named rules raised by the ledger triggers.
    """
    current: BaseException | None = exc
    while current is not None:
        name = getattr(current, "constraint_name", None)
        if name:
            return str(name)
        current = getattr(current, "orig", None) or current.__cause__
    return None
