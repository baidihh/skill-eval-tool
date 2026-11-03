"""Initial local evaluation schema. Existing pre-migration development DBs are adopted safely."""
from alembic import op
from app.schema import SCHEMA_DDL
revision='0001'
down_revision=None
branch_labels=None
depends_on=None

def upgrade():
    for statement in SCHEMA_DDL:op.execute(statement)

def downgrade():
    raise RuntimeError('Destructive downgrade is unsupported; restore a verified backup instead.')
