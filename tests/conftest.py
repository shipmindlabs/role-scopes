"""Minimal Django configuration so the adapters can be imported in tests."""

from __future__ import annotations

import django
from django.conf import settings


def pytest_configure() -> None:
    if settings.configured:
        return
    settings.configure(
        DEBUG=False,
        SECRET_KEY="role-scopes-tests",
        DATABASES={},
        INSTALLED_APPS=[
            "django.contrib.contenttypes",
            "django.contrib.auth",
        ],
        USE_TZ=True,
    )
    django.setup()
