"""Repository voor klant-gebruikers (Supabase-Auth-account -> bedrijf)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User


def get_user(session: Session, user_id: uuid.UUID) -> User | None:
    return session.get(User, user_id)


def get_user_by_email(session: Session, email: str) -> User | None:
    return session.scalar(select(User).where(User.email == email.strip().lower()))


def list_users(session: Session, tenant_id: uuid.UUID) -> list[User]:
    return list(
        session.scalars(
            select(User).where(User.tenant_id == tenant_id).order_by(User.created_at)
        )
    )


def create_user(
    session: Session, *, user_id: uuid.UUID, tenant_id: uuid.UUID, email: str
) -> User:
    user = User(id=user_id, tenant_id=tenant_id, email=email.strip().lower())
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def delete_user(session: Session, user_id: uuid.UUID) -> bool:
    user = session.get(User, user_id)
    if user is None:
        return False
    session.delete(user)
    session.commit()
    return True
