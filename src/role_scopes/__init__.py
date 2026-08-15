"""Multi-actor authorization primitives for Django backends."""

from role_scopes.actors import (
    ACTOR_PERMISSIONS,
    Actor,
    Permission,
    actors_with,
    has_permission,
    permissions_for,
)

__all__ = [
    "ACTOR_PERMISSIONS",
    "Actor",
    "Permission",
    "__version__",
    "actors_with",
    "has_permission",
    "permissions_for",
]

__version__ = "0.1.0"
