"""Idempotent column additions for demo volumes created before this version.

Only nullable columns are added, so existing rows stay valid. Real deployments
should replace this with a versioned migration tool.
"""

from sqlalchemy import inspect, text

from src.config.settings import engine
from src.models.tables import schema

ADDITIONS = {
    'business_runs': {
        'payload': 'JSON',
        'payload_digest': 'VARCHAR(64)',
        'version': 'INTEGER',
        'attempts': 'INTEGER',
        'lease_expires_at': 'VARCHAR(32)',
    },
    'business_evidence': {
        'payload_digest': 'VARCHAR(64)',
        'version': 'INTEGER',
        'attempt': 'INTEGER',
        'created_at': 'VARCHAR(32)',
    },
    'audit_events': {
        'case_id': 'INTEGER',
        'run_id': 'INTEGER',
        'evidence_id': 'INTEGER',
    },
}


def reconcile(engine=None):
    engine = engine or globals()['engine']
    schema.create_all(engine)
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, columns in ADDITIONS.items():
            if table not in existing:
                continue
            present = {column['name'] for column in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name not in present:
                    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}'))
