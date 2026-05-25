from __future__ import annotations

from peewee import DatabaseProxy, SqliteDatabase

db_proxy = DatabaseProxy()


def init_db(database_path: str) -> SqliteDatabase:
    database = SqliteDatabase(database_path)
    db_proxy.initialize(database)
    return database


def get_db() -> DatabaseProxy:
    return db_proxy
