"""
Startup hooks for the CycleWorks scheduling system.

Currently ensures that at least one Django superuser exists so admins can log
in to the Django admin UI. This is a lightweight helper used on server
startup; database errors are swallowed so the app does not crash if the DB is
not ready (e.g. before migrations).
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import DatabaseError, OperationalError
import logging


logger = logging.getLogger(__name__)


def ensure_default_superuser() -> None:
    """
    Ensure there is at least one superuser.

    Creates a default admin user if none exists:
    - username: admin
    - email: roshan@toroid.in
    - password: admin123

    Wrapped in broad exception handling so startup is not blocked by database
    issues (for example, when migrations have not yet been applied).
    """
    try:
        engine = settings.DATABASES["default"]["ENGINE"]
        logger.info("Database engine in use: %s", engine)
    except Exception:
        pass

    try:
        User = get_user_model()
        if User.objects.filter(is_superuser=True).exists():
            return

        User.objects.create_superuser(
            username="admin",
            email="roshan@toroid.in",
            password="admin123",
        )
    except (DatabaseError, OperationalError, Exception):
        # Silently ignore any errors so that application startup is not blocked.
        # This can be revisited once migration/bootstrapping is more structured.
        return

