"""SQLite: chats, memory facts, documents (full-text search) and the gallery."""
import sqlite3
import time
from contextlib import closing

from .config import DATA

DB_PATH = DATA / "app.db"


def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA secure_delete=ON")  # deleted chats / facts are overwritten with zeros, not just unlinked
    return con


def init() -> None:
    with closing(db()) as con:
        # write-ahead log: a deleted row is never copied into a side file first (the old rollback journal did)
        con.execute("PRAGMA journal_mode=WAL")
    with closing(db()) as con, con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS chats(id TEXT PRIMARY KEY, title TEXT, created REAL, updated REAL);
        CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT, role TEXT,
            content TEXT, extra TEXT, created REAL);
        CREATE INDEX IF NOT EXISTS idx_msg_chat ON messages(chat_id);
        CREATE TABLE IF NOT EXISTS facts(id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, name TEXT, chars INTEGER, created REAL);
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(doc_id UNINDEXED, text);
        CREATE TABLE IF NOT EXISTS gallery(id TEXT PRIMARY KEY, kind TEXT, file TEXT, prompt TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS learned(text TEXT PRIMARY KEY, route TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS projects(chat_id TEXT PRIMARY KEY, data TEXT, updated REAL);
        CREATE TABLE IF NOT EXISTS ratings(msg_id INTEGER PRIMARY KEY, chat_id TEXT, rating INTEGER, question TEXT,
            answer TEXT, reason TEXT, created REAL, vec BLOB);
        """)
        con.execute("INSERT INTO chunks(chunks, rank) VALUES('secure-delete', 1)")  # a deleted document leaves no words


def q(sql: str, args: tuple = ()) -> list[dict]:
    with closing(db()) as con:
        return [dict(r) for r in con.execute(sql, args).fetchall()]


def run(sql: str, args: tuple = ()) -> None:
    with closing(db()) as con, con:
        con.execute(sql, args)


def insert(sql: str, args: tuple = ()) -> int:
    with closing(db()) as con, con:
        return con.execute(sql, args).lastrowid


def many(sql: str, rows: list[tuple]) -> None:
    with closing(db()) as con, con:
        con.executemany(sql, rows)


def add_gallery(gid: str, kind: str, file: str, prompt: str) -> None:
    run("INSERT OR IGNORE INTO gallery VALUES (?,?,?,?,?)", (gid, kind, file, prompt, time.time()))
