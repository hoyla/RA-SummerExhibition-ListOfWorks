"""
Request-scoped user context.

Provides a ``contextvars.ContextVar`` that holds the email of the currently
authenticated user.  This is set by the ``UserContextMiddleware`` in main.py
and read automatically by the ``AuditLog`` SQLAlchemy ``before_insert`` event
so that every audit entry records who performed the action — without any
changes to individual route handlers.
"""

from contextvars import ContextVar

# Holds the current user's email for the duration of a request.
# Default is "anonymous" for local-dev / no-auth mode.
current_user_email: ContextVar[str] = ContextVar(
    "current_user_email", default="anonymous"
)
