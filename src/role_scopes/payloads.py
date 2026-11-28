"""Scoping a write: the values a new row must carry to be the actor's own.

A check says what an actor may do, a slice which rows are theirs, an ownership
check whether the row in hand is. A create route asks the same question about a
row that does not exist yet, so nothing can be fetched and compared: the values
are read from the same slice declaration instead, which is what makes the
``store_id`` an operator may not see the one it may not write either.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any

from role_scopes.actors import Actor, Permission
from role_scopes.checks import Decision, Denial, PermissionDenied, Rule, check
from role_scopes.scopes import (
    MEMBERSHIP_LOOKUP,
    Scope,
    ScopeKind,
    resource_of,
    scope_for,
    split_lookup,
)

__all__ = [
    "UnstampableScope",
    "check_payload",
    "require_payload",
    "scope_defaults",
    "scope_payload",
]

_MISSING = object()


class UnstampableScope(ValueError):
    """The declared slice names no value a new row could carry to land inside it."""


def _label(value: object) -> str:
    return value.value if isinstance(value, Enum) else str(value)


def _ensure_stampable(
    scope: Scope, resource: str, lookup: str, path: str, trailing: str | None
) -> None:
    if trailing == MEMBERSHIP_LOOKUP:
        raise UnstampableScope(
            f"scope {scope.label!r} narrows {path!r} by membership, which does not "
            f"say which value a new {resource} carries, so the payload has to name it"
        )
    if "__" in path:
        raise UnstampableScope(
            f"scope {scope.label!r} narrows {lookup!r}, which is a field of a "
            f"related row rather than of the new {resource}"
        )


def scope_defaults(
    actor: Actor | str,
    action: Permission | str,
    principal: Any = None,
) -> dict[str, Any]:
    """Return the field values a new row must carry to be inside the slice.

    An actor reaching everything constrains nothing and gets an empty mapping.
    Raises :class:`UnstampableScope` for a slice that names no value a single
    new row could carry: a resource with no declared slice, a lookup spanning a
    relation, or a membership slice, where a principal covering several stores
    does not say which one a new row belongs to. Raises
    :class:`~role_scopes.MissingScopeKey` when the principal does not carry an
    attribute the slice filters on.
    """
    scope = scope_for(actor, action)
    resource = resource_of(action)
    if scope.kind is ScopeKind.EVERYTHING:
        return {}
    if scope.kind is ScopeKind.NOTHING:
        raise UnstampableScope(
            f"no {resource} slice is declared for {_label(actor)}, so no values "
            f"place a new {resource} inside it"
        )

    fields: list[tuple[str, str]] = []
    for lookup, _attribute in scope.lookups:
        path, trailing = split_lookup(lookup)
        _ensure_stampable(scope, resource, lookup, path, trailing)
        fields.append((lookup, path))

    expected = scope.filters(principal)
    return {path: expected[lookup] for lookup, path in fields}


def check_payload(
    actor: Actor | str,
    action: Permission | str,
    payload: Mapping[str, Any],
    principal: Any = None,
) -> Decision:
    """Decide whether ``payload`` describes a row inside the actor's slice.

    The permission is checked first, then every value the payload carries for a
    field the slice narrows on is compared against it, by membership where the
    lookup declares it. A field the payload leaves out is not a denial: it is
    the field :func:`scope_defaults` fills, which is why a create route uses the
    pair rather than this check alone. Raises
    :class:`~role_scopes.MissingScopeKey` when the principal does not carry an
    attribute the slice filters on.
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
            Denial(decision.actor, decision.action, Rule.PAYLOAD_SCOPED, reason),
        )

    if scope.kind is ScopeKind.EVERYTHING:
        return decision
    if scope.kind is ScopeKind.NOTHING:
        return denied(f"no {resource} slice is declared for {decision.actor}")

    expected = scope.filters(principal)
    for lookup, _attribute in scope.lookups:
        path, trailing = split_lookup(lookup)
        value = payload.get(path, _MISSING)
        if value is _MISSING:
            continue
        inside = (
            value in expected[lookup]
            if trailing == MEMBERSHIP_LOOKUP
            else value == expected[lookup]
        )
        if not inside:
            return denied(f"{path!r} places this new {resource} outside {scope.label}")

    return decision


def require_payload(
    actor: Actor | str,
    action: Permission | str,
    payload: Mapping[str, Any],
    principal: Any = None,
) -> None:
    """Raise :class:`~role_scopes.PermissionDenied` unless ``payload`` is in slice."""
    decision = check_payload(actor, action, payload, principal)
    if decision.denial is not None:
        raise PermissionDenied(decision.denial)


def scope_payload(
    actor: Actor | str,
    action: Permission | str,
    payload: Mapping[str, Any],
    principal: Any = None,
) -> dict[str, Any]:
    """Return ``payload`` with the values of the actor's slice stamped on it.

    One call for a create route: the capability is checked, a payload naming a
    value outside the slice raises :class:`~role_scopes.PermissionDenied`
    rather than being quietly overwritten, and the fields it left out are
    filled from the slice. A field the slice cannot express as a single value
    and the payload does not name raises :class:`UnstampableScope`, because
    returning the payload unchanged would create a row nobody reaches.
    """
    require_payload(actor, action, payload, principal)

    scope = scope_for(actor, action)
    if scope.kind is not ScopeKind.OWN:
        return dict(payload)

    resource = resource_of(action)
    expected = scope.filters(principal)
    stamped = dict(payload)
    for lookup, _attribute in scope.lookups:
        path, trailing = split_lookup(lookup)
        if path in stamped:
            continue
        _ensure_stampable(scope, resource, lookup, path, trailing)
        stamped[path] = expected[lookup]
    return stamped
