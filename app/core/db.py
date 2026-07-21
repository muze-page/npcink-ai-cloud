from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.models import Base
from app.core.redaction import safe_exception_type


@lru_cache(maxsize=8)
def get_engine(database_url: str) -> Engine:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(
        database_url,
        future=True,
        hide_parameters=True,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


@lru_cache(maxsize=8)
def get_session_factory(database_url: str) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(database_url), autoflush=False, expire_on_commit=False)


@contextmanager
def get_session(database_url: str) -> Iterator[Session]:
    session = get_session_factory(database_url)()

    try:
        yield session
    finally:
        session.close()


def init_schema(database_url: str) -> None:
    # Test-only helper for sqlite fixtures and focused local harnesses.
    Base.metadata.create_all(bind=get_engine(database_url))


def dispose_engine(database_url: str) -> None:
    get_engine(database_url).dispose()
    get_engine.cache_clear()
    get_session_factory.cache_clear()


def check_database_connection(database_url: str) -> tuple[bool, str]:
    try:
        engine = get_engine(database_url)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True, "database is reachable"
    except Exception as error:
        return False, safe_exception_type(error)


def require_database_connection(database_url: str) -> None:
    ok, detail = check_database_connection(database_url)
    if ok:
        return
    raise RuntimeError(f"database is not reachable: {detail}")
