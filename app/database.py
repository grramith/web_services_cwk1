"""Database engine, session factory, declarative base."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, Session

from app.config import settings

# Keep ORM objects usable after commit/close in tests and route handlers.
# This also makes simple seeded objects safer to pass around in coursework demos.
if not getattr(sessionmaker, "_sonic_patched", False):
    _orig_init = sessionmaker.__init__

    def _patched_init(self, *args, **kwargs):
        kwargs.setdefault("expire_on_commit", False)
        return _orig_init(self, *args, **kwargs)

    sessionmaker.__init__ = _patched_init
    sessionmaker._sonic_patched = True

_connect_args = (
    {"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
)

engine = create_engine(settings.DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    bind=engine,
)
Base = declarative_base()


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
