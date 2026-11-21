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
from role_scopes.principals import (
    NO_ACTOR,
    check_any,
    check_object_any,
    owns_any,
    require_any,
    require_object_any,
    scope_queryset_any,
)
from role_scopes.scopes import (
    ACTOR_SCOPES,
    RESOURCES,
    MissingScopeKey,
    Scope,
    ScopeDeclarationError,
    ScopeKind,
    resource_of,
    scope_for,
    scope_queryset,
)
from role_scopes.verify import (
    Finding,
    FindingKind,
    verify_declarations,
)

__all__ = [
    "ACTOR_PERMISSIONS",
    "ACTOR_SCOPES",
    "NO_ACTOR",
    "RESOURCES",
    "Actor",
    "Decision",
    "Denial",
    "Finding",
    "FindingKind",
    "MissingObjectKey",
    "MissingScopeKey",
    "Permission",
    "PermissionDenied",
    "Rule",
    "Scope",
    "ScopeDeclarationError",
    "ScopeKind",
    "__version__",
    "actors_with",
    "check",
    "check_any",
    "check_object",
    "check_object_any",
    "has_permission",
    "owns",
    "owns_any",
    "permissions_for",
    "require",
    "require_any",
    "require_object",
    "require_object_any",
    "resource_of",
    "scope_for",
    "scope_queryset",
    "scope_queryset_any",
    "verify_declarations",
]

__version__ = "0.1.0"
