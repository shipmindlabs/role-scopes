"""Object ownership checks: whether the row in hand belongs to the actor.

A permission says what an actor may do; it never says which objects are theirs.
Ownership is read from the same slice declarations that narrow querysets, so
the row a list view hides is exactly the row a detail view refuses.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from role_scopes.actors import Actor, Permission
from role_scopes.checks import Decision, Denial, PermissionDenied, Rule, check
from role_scopes.scopes import ScopeKind, resource_of, scope_for

__all__ = [
    "MissingObjectKey",
    "check_object",
    "owns",
    "require_object",
]

_MISSING = object()


class MissingObjectKey(LookupError):
    """The object lacks an attribute a declared scope narrows on."""


def _object_value(obj: Any, lookup: str) -> Any:
    current: Any = obj
    for part in lookup.split("__"):
        if isinstance(current, Mapping):
            current = current.get(part, _MISSING)
        else:
            current = getattr(current, part, _MISSING)
        if current is _MISSING or current is None:
            return current
    return current


def check_object(
    actor: Actor | str,
    action: Permission | str,
    obj: Any,
    principal: Any = None,
) -> Decision:
    """Decide whether ``actor`` may perform ``action`` on ``obj``.

    The permission is checked first, then the object is compared against the
    slice declared for that actor and resource. An actor whose slice is
    ``everything`` reaches every row; a resource with no declared slice reaches
    none. Raises :class:`~role_scopes.MissingScopeKey` when the principal does
    not carry an attribute the slice filters on, and :class:`MissingObjectKey`
    when the object does not carry the field the slice narrows on.
    """
    decision = check(actor, action)
    if decision.denial is not None:
        return decision

    resource = resource_of(action)
    scope = scope_for(actor, action)

    def denied(reason: str) -> Decision:
        return Decision(
            decision.actor,
            decision.action,
            Denial(decision.actor, decision.action, Rule.OBJECT_OWNED, reason),
        )

    if scope.kind is ScopeKind.EVERYTHING:
        return decision
    if scope.kind is ScopeKind.NOTHING:
        return denied(f"no {resource} slice is declared for {decision.actor}")

    expected = scope.filters(principal)
    for lookup, _attribute in scope.lookups:
        value = _object_value(obj, lookup)
        if value is _MISSING:
            raise MissingObjectKey(
                f"scope {scope.label!r} needs {lookup!r} on the {resource}"
            )
        if value != expected[lookup]:
            return denied(f"this {resource} is outside {scope.label}")

    return decision


def owns(
    actor: Actor | str,
    action: Permission | str,
    obj: Any,
    principal: Any = None,
) -> bool:
    """Tell whether ``obj`` is within the slice ``principal`` reaches."""
    return check_object(actor, action, obj, principal).allowed


def require_object(
    actor: Actor | str,
    action: Permission | str,
    obj: Any,
    principal: Any = None,
) -> None:
    """Raise :class:`PermissionDenied` unless ``actor`` may act on ``obj``."""
    decision = check_object(actor, action, obj, principal)
    if decision.denial is not None:
        raise PermissionDenied(decision.denial)
