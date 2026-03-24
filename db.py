import sqlite3
import threading

DB_PATH = "ble_tracker.db"
_local = threading.local()


def _conn():
    if not hasattr(_local, "conn"):
        _local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
    return _local.conn


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS gateway_names (
            mac  TEXT PRIMARY KEY,
            name TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tag_names (
            mac  TEXT PRIMARY KEY,
            name TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()


def get_setting(key, default=""):
    row = _conn().execute(
        "SELECT value FROM settings WHERE key = ?", (key,)
    ).fetchone()
    return row["value"] if row else default


def set_setting(key, value):
    _conn().execute(
        "INSERT INTO settings(key, value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    _conn().commit()


def all_settings():
    rows = _conn().execute("SELECT key, value FROM settings").fetchall()
    return {r["key"]: r["value"] for r in rows}


def get_name(table, mac):
    row = _conn().execute(
        f"SELECT name FROM {table} WHERE mac = ?", (mac.upper(),)
    ).fetchone()
    return row["name"] if row else None


def set_name(table, mac, name):
    _conn().execute(
        f"INSERT INTO {table}(mac, name) VALUES(?,?) "
        f"ON CONFLICT(mac) DO UPDATE SET name=excluded.name",
        (mac.upper(), name),
    )
    _conn().commit()


def all_names(table):
    rows = _conn().execute(f"SELECT mac, name FROM {table}").fetchall()
    return {r["mac"]: r["name"] for r in rows}
