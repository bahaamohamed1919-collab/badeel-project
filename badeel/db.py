"""Database access layer.

Every other file talks to the database through the small helpers here, and
every query uses "?" placeholders (parameterised queries), so user input is
never glued into SQL text. That is what prevents SQL injection.
"""
import os
import sqlite3
from datetime import datetime, timedelta, timezone

from flask import current_app, g


def get_db():
    """One connection per request, stored on flask.g and closed afterwards."""
    if "db" not in g:
        con = sqlite3.connect(current_app.config["DATABASE"])
        con.row_factory = sqlite3.Row            # rows behave like dicts
        con.execute("PRAGMA foreign_keys = ON")  # enforce relations
        g.db = con
    return g.db


def close_db(_exc=None):
    con = g.pop("db", None)
    if con is not None:
        con.close()


def query(sql, args=()):
    return get_db().execute(sql, args).fetchall()


def one(sql, args=()):
    return get_db().execute(sql, args).fetchone()


def execute(sql, args=()):
    return get_db().execute(sql, args)


def commit():
    get_db().commit()


def init_db():
    path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(path, encoding="utf-8") as f:
        get_db().executescript(f.read())
    # Databases created by an older version get the new columns added.
    columns = {r["name"] for r in query("PRAGMA table_info(users)")}
    if "consent_at" not in columns:
        execute("ALTER TABLE users ADD COLUMN consent_at TEXT")
    if "pack_count" not in {r["name"] for r in query("PRAGMA table_info(drugs)")}:
        execute("ALTER TABLE drugs ADD COLUMN pack_count INTEGER")
    commit()


def now(offset_minutes=0):
    """UTC timestamp as text, e.g. 2026-11-11 10:30:00 (sorts correctly)."""
    t = datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)
    return t.strftime("%Y-%m-%d %H:%M:%S")


def get_setting(key, default=None):
    row = one("SELECT value FROM settings WHERE key = ?", (key,))
    return row["value"] if row else default


def set_setting(key, value):
    execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


def bump_data_version():
    """Called after any change to drugs so the search index rebuilds itself."""
    set_setting("data_version", int(get_setting("data_version", "0")) + 1)
