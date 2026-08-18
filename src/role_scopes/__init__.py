"""Multi-actor authorization primitives for Django backends."""

from role_scopes.actors import (
    ACTOR_PERMISSIONS,
    Actor,
    Permission,
    actors_with,
    has_permission,
    permissions_for,
)
from role_scopes.checks import (
    Decision,
    Denial,
    PermissionDenied,
    Rule,
    check,
    require,
)

__all__ = [
    "ACTOR_PERMISSIONS",
    "Actor",
    "Decision",
    "Denial",
    "Permission",
    "PermissionDenied",
    "Rule",
    "__version__",
    "actors_with",
    "check",
    "has_permission",
    "permissions_for",
    "require",
]

__version__ = "0.1.0"
