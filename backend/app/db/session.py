"""Database-engine en sessiefabriek.

create_engine maakt geen verbinding bij import; pas bij eerste gebruik. De
sessiefabriek wordt gecached zodat de app er één engine op nahoudt.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


def create_session_factory(database_url: str) -> sessionmaker[Session]:
    engine = create_engine(database_url, pool_pre_ping=True, future=True)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return create_session_factory(get_settings().database_url)


def get_session() -> Iterator[Session]:
    """FastAPI-dependency: levert een sessie en sluit die na de request."""
    factory = get_session_factory()
    with factory() as session:
        yield session
