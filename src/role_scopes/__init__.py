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
from role_scopes.ownership import (
    MissingObjectKey,
    check_object,
    owns,
    require_object,
)
from role_scopes.scopes import (
    ACTOR_SCOPES,
    RESOURCES,
    MissingScopeKey,
    Scope,
    ScopeKind,
    resource_of,
    scope_for,
    scope_queryset,
)

__all__ = [
    "ACTOR_PERMISSIONS",
    "ACTOR_SCOPES",
    "RESOURCES",
    "Actor",
    "Decision",
    "Denial",
    "MissingObjectKey",
    "MissingScopeKey",
    "Permission",
    "PermissionDenied",
    "Rule",
    "Scope",
    "ScopeKind",
    "__version__",
    "actors_with",
    "check",
    "check_object",
    "has_permission",
    "owns",
    "permissions_for",
    "require",
    "require_object",
    "resource_of",
    "scope_for",
    "scope_queryset",
]

__version__ = "0.1.0"
