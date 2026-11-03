"""Durable logical calls, send intentions and versioned supplier usage."""
from alembic import op

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    for statement in [
        '''CREATE TABLE ledger_calls (
            id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES experiments(id),
            case_id TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('expert','judge')),
            batch_id TEXT NOT NULL, namespace TEXT NOT NULL, submit_key TEXT NOT NULL,
            request_hash TEXT NOT NULL, created_at TEXT NOT NULL,
            UNIQUE(namespace, submit_key))''',
        '''CREATE TABLE ledger_external_runs (
            namespace TEXT NOT NULL, external_run_id TEXT NOT NULL,
            call_id TEXT NOT NULL UNIQUE REFERENCES ledger_calls(id),
            PRIMARY KEY(namespace, external_run_id))''',
        '''CREATE TABLE ledger_transports (
            id TEXT PRIMARY KEY, call_id TEXT NOT NULL REFERENCES ledger_calls(id),
            seq INTEGER NOT NULL, operation_id TEXT NOT NULL, request_hash TEXT NOT NULL,
            state TEXT NOT NULL, recovery TEXT NOT NULL, created_at TEXT NOT NULL,
            UNIQUE(call_id, seq), UNIQUE(call_id, operation_id))''',
        '''CREATE TABLE usage_observations (
            id TEXT PRIMARY KEY, namespace TEXT NOT NULL, item_id TEXT NOT NULL,
            version INTEGER NOT NULL, supplier_event_id TEXT NOT NULL,
            call_id TEXT NOT NULL REFERENCES ledger_calls(id),
            payload TEXT NOT NULL, content_hash TEXT NOT NULL, created_at TEXT NOT NULL,
            UNIQUE(namespace, item_id, version), UNIQUE(namespace, supplier_event_id))''',
        'CREATE INDEX ledger_case_batch ON ledger_calls(experiment_id,case_id,kind,batch_id)',
        'CREATE INDEX usage_call ON usage_observations(call_id)',
    ]:
        op.execute(statement)
    for table in ('ledger_calls', 'ledger_transports', 'usage_observations', 'ledger_external_runs'):
        for action in ('UPDATE', 'DELETE'):
            op.execute(f'CREATE TRIGGER immutable_{table}_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,"immutable ledger record"); END')


def downgrade():
    raise RuntimeError('Destructive downgrade unsupported; use a verified backup.')
