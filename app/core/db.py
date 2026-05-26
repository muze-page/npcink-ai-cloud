from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.models import Base


@lru_cache(maxsize=8)
def get_engine(database_url: str) -> Engine:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(
        database_url,
        future=True,
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
    engine = get_engine(database_url)

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True, "database is reachable"
    except SQLAlchemyError as error:
        return False, str(error)


def require_database_connection(database_url: str) -> None:
    ok, detail = check_database_connection(database_url)
    if ok:
        return
    raise RuntimeError(f"database is not reachable: {detail}")
