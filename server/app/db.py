"""SQLAlchemy engine and session management.

schema.sql is the single source of truth; models.py conforms to it. The app
never creates or migrates tables.
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

_engine = None
SessionLocal = scoped_session(sessionmaker(expire_on_commit=False))


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(
            os.environ["DATABASE_URL"], pool_pre_ping=True, future=True
        )
        SessionLocal.configure(bind=_engine)
    return _engine


def init_app(app) -> None:
    get_engine()

    @app.teardown_appcontext
    def remove_session(exc=None):  # noqa: ANN001
        SessionLocal.remove()
