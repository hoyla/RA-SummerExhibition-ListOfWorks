"""
Shared FastAPI dependencies used by all route modules.
"""

from backend.app.db import SessionLocal


def get_db():
    """Yield a SQLAlchemy session and close it when the request is done."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
