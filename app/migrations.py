"""Minimal versioned migrations: each migration runs once and is recorded in schema_migrations."""
from sqlalchemy import text
from .db import Base, engine

MIGRATIONS = [
    ("001_initial_schema", lambda conn: Base.metadata.create_all(conn)),
]


def migrate() -> list[str]:
    applied_now = []
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations (version VARCHAR(100) PRIMARY KEY)"))
        done = {r[0] for r in conn.execute(text("SELECT version FROM schema_migrations"))}
        for version, fn in MIGRATIONS:
            if version not in done:
                fn(conn)
                conn.execute(text("INSERT INTO schema_migrations (version) VALUES (:v)"), {"v": version})
                applied_now.append(version)
    return applied_now


if __name__ == "__main__":
    print("applied:", migrate() or "nothing (up to date)")
