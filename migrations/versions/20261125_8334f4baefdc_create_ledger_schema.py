"""create ledger schema

Creates accounts, journal_entries and postings, plus database-enforced ledger rules:

1. Balanced entries: every journal entry has >= 2 postings that sum to exactly zero,
   checked at COMMIT (deferred constraint triggers), so all legs can be inserted first.
2. Append-only ledger: journal entries and postings can never be updated or deleted.
3. Trigger-maintained balances: inserting a posting atomically adjusts the account's
   balance under a row lock; balances cannot be written directly.
4. No overdrafts on customer accounts (CHECK constraint on the running balance).
5. Currency consistency through composite foreign keys (see the table definitions).

Revision ID: 8334f4baefdc
Revises:
Create Date: 2026-11-25 16:42:02.866881+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8334f4baefdc"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _plpgsql_function(signature: str, returns: str, body: str) -> str:
    return f"CREATE FUNCTION {signature} RETURNS {returns}\nLANGUAGE plpgsql AS $$\n{body}\n$$"


# One statement per entry: asyncpg executes a single statement per call.
LEDGER_FUNCTIONS = (
    # (1) Balanced journal entries: >= 2 postings summing to exactly zero.
    _plpgsql_function(
        "ledger_check_journal_balanced(p_journal_entry_id uuid)",
        "void",
        """
DECLARE
    v_postings integer;
    v_total    numeric;
BEGIN
    SELECT count(*), coalesce(sum(amount), 0)
      INTO v_postings, v_total
      FROM postings
     WHERE journal_entry_id = p_journal_entry_id;

    IF v_postings < 2 THEN
        RAISE EXCEPTION 'journal entry % needs at least two postings, found %',
            p_journal_entry_id, v_postings
            USING ERRCODE = 'check_violation', CONSTRAINT = 'journal_entry_balanced';
    END IF;
    IF v_total <> 0 THEN
        RAISE EXCEPTION 'journal entry % is unbalanced: postings sum to %',
            p_journal_entry_id, v_total
            USING ERRCODE = 'check_violation', CONSTRAINT = 'journal_entry_balanced';
    END IF;
END;""",
    ),
    _plpgsql_function(
        "ledger_journal_entries_balanced()",
        "trigger",
        """
BEGIN
    PERFORM ledger_check_journal_balanced(NEW.id);
    RETURN NULL;
END;""",
    ),
    _plpgsql_function(
        "ledger_postings_balanced()",
        "trigger",
        """
BEGIN
    PERFORM ledger_check_journal_balanced(NEW.journal_entry_id);
    RETURN NULL;
END;""",
    ),
    # (2) Append-only ledger.
    _plpgsql_function(
        "ledger_forbid_modification()",
        "trigger",
        """
BEGIN
    RAISE EXCEPTION '% is append-only: % is not allowed (post a reversal instead)',
        TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'integrity_constraint_violation', CONSTRAINT = 'ledger_append_only';
END;""",
    ),
    # (3) Trigger-maintained balances.
    _plpgsql_function(
        "ledger_apply_posting_to_balance()",
        "trigger",
        """
BEGIN
    -- Row-locks the account: concurrent postings to it serialise here, and the
    -- non-negative CHECK is evaluated against the latest committed balance.
    UPDATE accounts
       SET balance = balance + NEW.amount,
           updated_at = now()
     WHERE id = NEW.account_id;
    RETURN NULL;
END;""",
    ),
    _plpgsql_function(
        "ledger_guard_account_balance()",
        "trigger",
        """
BEGIN
    IF TG_OP = 'INSERT' AND NEW.balance <> 0 THEN
        RAISE EXCEPTION 'accounts must be opened with a zero balance'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'balance_managed_by_ledger';
    END IF;
    -- Depth 1 = a direct UPDATE statement; depth 2 = called from the posting trigger.
    IF TG_OP = 'UPDATE' AND NEW.balance IS DISTINCT FROM OLD.balance
       AND pg_trigger_depth() < 2 THEN
        RAISE EXCEPTION 'account balance can only change by posting journal entries'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'balance_managed_by_ledger';
    END IF;
    RETURN NEW;
END;""",
    ),
)

LEDGER_TRIGGERS = (
    # Deferred to COMMIT so all legs of an entry can be inserted before the check runs.
    """CREATE CONSTRAINT TRIGGER trg_journal_entries_balanced
    AFTER INSERT ON journal_entries DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION ledger_journal_entries_balanced()""",
    """CREATE CONSTRAINT TRIGGER trg_postings_balanced
    AFTER INSERT ON postings DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION ledger_postings_balanced()""",
    """CREATE TRIGGER trg_journal_entries_append_only
    BEFORE UPDATE OR DELETE ON journal_entries
    FOR EACH ROW EXECUTE FUNCTION ledger_forbid_modification()""",
    """CREATE TRIGGER trg_postings_append_only
    BEFORE UPDATE OR DELETE ON postings
    FOR EACH ROW EXECUTE FUNCTION ledger_forbid_modification()""",
    """CREATE TRIGGER trg_postings_apply_to_balance
    AFTER INSERT ON postings
    FOR EACH ROW EXECUTE FUNCTION ledger_apply_posting_to_balance()""",
    """CREATE TRIGGER trg_accounts_guard_balance
    BEFORE INSERT OR UPDATE ON accounts
    FOR EACH ROW EXECUTE FUNCTION ledger_guard_account_balance()""",
)

DROP_LEDGER = (
    "DROP TRIGGER IF EXISTS trg_accounts_guard_balance ON accounts",
    "DROP TRIGGER IF EXISTS trg_postings_apply_to_balance ON postings",
    "DROP TRIGGER IF EXISTS trg_postings_append_only ON postings",
    "DROP TRIGGER IF EXISTS trg_journal_entries_append_only ON journal_entries",
    "DROP TRIGGER IF EXISTS trg_postings_balanced ON postings",
    "DROP TRIGGER IF EXISTS trg_journal_entries_balanced ON journal_entries",
    "DROP FUNCTION IF EXISTS ledger_guard_account_balance()",
    "DROP FUNCTION IF EXISTS ledger_apply_posting_to_balance()",
    "DROP FUNCTION IF EXISTS ledger_forbid_modification()",
    "DROP FUNCTION IF EXISTS ledger_postings_balanced()",
    "DROP FUNCTION IF EXISTS ledger_journal_entries_balanced()",
    "DROP FUNCTION IF EXISTS ledger_check_journal_balanced(uuid)",
)


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                "customer", "system", name="account_type", native_enum=False, create_constraint=True
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "frozen",
                "closed",
                name="account_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="active",
            nullable=False,
        ),
        sa.Column("currency", sa.CHAR(length=3), nullable=False),
        sa.Column("balance", sa.Numeric(precision=19, scale=4), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name=op.f("ck_accounts_currency_iso_4217")),
        sa.CheckConstraint(
            "type = 'system' OR balance >= 0",
            name=op.f("ck_accounts_customer_balance_non_negative"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_accounts")),
        sa.UniqueConstraint("id", "currency", name=op.f("uq_accounts_id_currency")),
    )
    op.create_table(
        "journal_entries",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "entry_type",
            sa.Enum(
                "deposit",
                "withdrawal",
                "transfer",
                "reversal",
                name="journal_entry_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("currency", sa.CHAR(length=3), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'", name=op.f("ck_journal_entries_currency_iso_4217")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_journal_entries")),
        sa.UniqueConstraint("id", "currency", name=op.f("uq_journal_entries_id_currency")),
    )
    op.create_table(
        "postings",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("journal_entry_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("currency", sa.CHAR(length=3), nullable=False),
        sa.Column("amount", sa.Numeric(precision=19, scale=4), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("amount <> 0", name=op.f("ck_postings_amount_non_zero")),
        sa.ForeignKeyConstraint(
            ["account_id", "currency"],
            ["accounts.id", "accounts.currency"],
            name=op.f("fk_postings_account_id_currency_accounts"),
        ),
        sa.ForeignKeyConstraint(
            ["journal_entry_id", "currency"],
            ["journal_entries.id", "journal_entries.currency"],
            name=op.f("fk_postings_journal_entry_id_currency_journal_entries"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_postings")),
    )
    op.create_index(
        op.f("ix_postings_account_id_created_at"),
        "postings",
        ["account_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_postings_journal_entry_id"), "postings", ["journal_entry_id"], unique=False
    )
    # asyncpg executes one statement per call.
    for statement in (*LEDGER_FUNCTIONS, *LEDGER_TRIGGERS):
        op.execute(statement)


def downgrade() -> None:
    for statement in DROP_LEDGER:
        op.execute(statement)
    op.drop_index(op.f("ix_postings_journal_entry_id"), table_name="postings")
    op.drop_index(op.f("ix_postings_account_id_created_at"), table_name="postings")
    op.drop_table("postings")
    op.drop_table("journal_entries")
    op.drop_table("accounts")
