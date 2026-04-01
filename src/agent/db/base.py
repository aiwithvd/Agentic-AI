"""SQLAlchemy declarative base and shared metadata."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared base class for all ORM models."""
