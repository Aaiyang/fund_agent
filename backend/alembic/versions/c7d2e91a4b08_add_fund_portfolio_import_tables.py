"""Add fund, watchlist, portfolio, transaction and holding import tables.

Revision ID: c7d2e91a4b08
Revises: b25d38b0cd7c
Create Date: 2026-09-19
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c7d2e91a4b08"  # pragma: allowlist secret
down_revision = "b25d38b0cd7c"  # pragma: allowlist secret
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the fund domain tables and their indexes."""
    op.create_table(
        "fund",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("fund_code", sa.String(length=12), nullable=False),
        sa.Column("fund_name", sa.String(length=200), nullable=False),
        sa.Column("fund_type", sa.String(length=50), nullable=True),
        sa.Column("company", sa.String(length=200), nullable=True),
        sa.Column("manager_name", sa.String(length=200), nullable=True),
        sa.Column("inception_date", sa.Date(), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("source_as_of", sa.Date(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("fund_code"),
    )
    op.create_index(op.f("ix_fund_fund_code"), "fund", ["fund_code"])
    op.create_index(op.f("ix_fund_fund_name"), "fund", ["fund_name"])

    op.create_table(
        "fund_nav",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("fund_code", sa.String(length=12), nullable=False),
        sa.Column("nav_date", sa.Date(), nullable=False),
        sa.Column("unit_nav", sa.Float(), nullable=True),
        sa.Column("accumulated_nav", sa.Float(), nullable=True),
        sa.Column("daily_return", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["fund_code"], ["fund.fund_code"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fund_code", "nav_date", name="uq_fund_nav_code_date"),
    )
    op.create_index(op.f("ix_fund_nav_fund_code"), "fund_nav", ["fund_code"])
    op.create_index(op.f("ix_fund_nav_nav_date"), "fund_nav", ["nav_date"])

    op.create_table(
        "watchlist",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("fund_code", sa.String(length=12), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "fund_code", name="uq_watchlist_user_fund"),
    )
    op.create_index(op.f("ix_watchlist_user_id"), "watchlist", ["user_id"])
    op.create_index(op.f("ix_watchlist_fund_code"), "watchlist", ["fund_code"])

    op.create_table(
        "watchlist_group",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_watchlist_group_user_id"), "watchlist_group", ["user_id"])

    op.create_table(
        "watchlist_group_item",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("watchlist_id", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["watchlist_group.id"]),
        sa.ForeignKeyConstraint(["watchlist_id"], ["watchlist.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_watchlist_group_item_group_id"), "watchlist_group_item", ["group_id"])
    op.create_index(op.f("ix_watchlist_group_item_watchlist_id"), "watchlist_group_item", ["watchlist_id"])

    op.create_table(
        "portfolio_account",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("source_app", sa.String(length=50), nullable=True),
        sa.Column("account_type", sa.String(length=30), nullable=False),
        sa.Column("import_mode", sa.String(length=30), nullable=False),
        sa.Column("last_imported_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_portfolio_account_user_id"), "portfolio_account", ["user_id"])

    op.create_table(
        "portfolio_position",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("fund_code", sa.String(length=12), nullable=False),
        sa.Column("shares", sa.Float(), nullable=True),
        sa.Column("cost_amount", sa.Float(), nullable=True),
        sa.Column("average_cost_nav", sa.Float(), nullable=True),
        sa.Column("market_value", sa.Float(), nullable=True),
        sa.Column("profit_loss", sa.Float(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["portfolio_account.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "fund_code", name="uq_position_account_fund"),
    )
    op.create_index(op.f("ix_portfolio_position_user_id"), "portfolio_position", ["user_id"])
    op.create_index(op.f("ix_portfolio_position_account_id"), "portfolio_position", ["account_id"])
    op.create_index(op.f("ix_portfolio_position_fund_code"), "portfolio_position", ["fund_code"])

    op.create_table(
        "transaction",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("fund_code", sa.String(length=12), nullable=False),
        sa.Column("transaction_type", sa.String(length=30), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("shares", sa.Float(), nullable=True),
        sa.Column("nav", sa.Float(), nullable=True),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("fee", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("external_transaction_id", sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["portfolio_account.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_transaction_user_id"), "transaction", ["user_id"])
    op.create_index(op.f("ix_transaction_account_id"), "transaction", ["account_id"])
    op.create_index(op.f("ix_transaction_fund_code"), "transaction", ["fund_code"])
    op.create_index(op.f("ix_transaction_trade_date"), "transaction", ["trade_date"])

    op.create_table(
        "holding_import",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("import_type", sa.String(length=20), nullable=False),
        sa.Column("source_app", sa.String(length=50), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("image_count", sa.Integer(), nullable=False),
        sa.Column("image_hashes", sa.JSON(), nullable=True),
        sa.Column("items_detected", sa.Integer(), nullable=False),
        sa.Column("items_confirmed", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["portfolio_account.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_holding_import_user_id"), "holding_import", ["user_id"])
    op.create_index(op.f("ix_holding_import_account_id"), "holding_import", ["account_id"])
    op.create_index(op.f("ix_holding_import_status"), "holding_import", ["status"])

    op.create_table(
        "holding_import_item",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("import_id", sa.String(length=32), nullable=False),
        sa.Column("raw_fund_name", sa.String(length=200), nullable=True),
        sa.Column("matched_fund_code", sa.String(length=12), nullable=True),
        sa.Column("matched_fund_name", sa.String(length=200), nullable=True),
        sa.Column("market_value", sa.Float(), nullable=True),
        sa.Column("shares", sa.Float(), nullable=True),
        sa.Column("cost_amount", sa.Float(), nullable=True),
        sa.Column("average_cost_nav", sa.Float(), nullable=True),
        sa.Column("profit_loss", sa.Float(), nullable=True),
        sa.Column("profit_loss_rate", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("validation_status", sa.String(length=30), nullable=False),
        sa.Column("validation_issues", sa.JSON(), nullable=True),
        sa.Column("user_action", sa.String(length=20), nullable=True),
        sa.ForeignKeyConstraint(["import_id"], ["holding_import.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_holding_import_item_import_id"), "holding_import_item", ["import_id"])
    op.create_index(op.f("ix_holding_import_item_matched_fund_code"), "holding_import_item", ["matched_fund_code"])


def downgrade() -> None:
    """Drop the fund domain tables in reverse dependency order."""
    op.drop_table("holding_import_item")
    op.drop_table("holding_import")
    op.drop_table("transaction")
    op.drop_table("portfolio_position")
    op.drop_table("portfolio_account")
    op.drop_table("watchlist_group_item")
    op.drop_table("watchlist_group")
    op.drop_table("watchlist")
    op.drop_table("fund_nav")
    op.drop_table("fund")
