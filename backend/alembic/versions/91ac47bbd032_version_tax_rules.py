"""Allow multiple approved and historical versions for each tax rule code."""
from alembic import op

revision = "91ac47bbd032"
down_revision = "42723ca8a29c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("tax_rules_rule_code_key", "tax_rules", type_="unique")
    op.create_unique_constraint(
        "uq_tax_rule_code_version", "tax_rules", ["rule_code", "version"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_tax_rule_code_version", "tax_rules", type_="unique")
    op.create_unique_constraint("tax_rules_rule_code_key", "tax_rules", ["rule_code"])
