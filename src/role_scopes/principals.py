"""Principals wearing more than one hat.

The matrix has one row per audience, and a person is not always one row: the
support lead covers back-office at the weekend, a warehouse supervisor drives a
van when a courier calls in sick. The functions here read a collection of
actors against the same declarations and answer with whatever any one of them
reaches, so a project growing a second hat does not have to invent a row that
grants the union by hand.

A denial names one actor, so the one reported is the actor that reached
furthest through the rules: a stale role sitting in the collection never hides
why the real one was refused.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum
from typing import Any, TypeVar

from django.db.models import Q, QuerySet

from role_scopes.actors import Actor, Permission
from role_scopes.checks import Decision, Denial, PermissionDenied, Rule, check
from role_scopes.ownership import MissingObjectKey, check_object
from role_scopes.scopes import MissingScopeKey, ScopeKind, scope_for

__all__ = [
    "NO_ACTOR",
    "check_any",
    "check_object_any",
    "owns_any",
    "require_any",
    "require_object_any",
    "scope_queryset_any",
]

_QuerySetT = TypeVar("_QuerySetT", bound=QuerySet)

# The actor a denial names when the principal carried no role at all.
NO_ACTOR = "none"

# ``Rule`` is declared in the order the rules are applied, so the later a
# denial's rule, the further that actor got before being refused.
_REACH: dict[Rule, int] = {rule: index for index, rule in enumerate(Rule)}


def _label(value: object) -> str:
    return value.value if isinstance(value, Enum) else str(value)


def _reach(decision: Decision) -> int:
    denial = decision.denial
    return -1 if denial is None else _REACH[denial.rule]


def _without_actors(action: Permission | str) -> Decision:
    label = _label(action)
    return Decision(
        NO_ACTOR,
        label,
        Denial(NO_ACTOR, label, Rule.ACTOR_KNOWN, "no actor was given"),
    )


def check_any(actors: Iterable[Actor | str], action: Permission | str) -> Decision:
    """Decide whether any of ``actors`` may perform ``action``.

    The decision returned is the one that answered: the first actor allowed, or
    else the denial that reached furthest through the rules. An empty collection
    is a denial carrying the ``actor.known`` rule rather than an error.
    """
    furthest: Decision | None = None
    for actor in actors:
        decision = check(actor, action)
        if decision.allowed:
            return decision
        if furthest is None or _reach(decision) > _reach(furthest):
            furthest = decision
    return _without_actors(action) if furthest is None else furthest


def require_any(actors: Iterable[Actor | str], action: Permission | str) -> None:
    """Raise :class:`~role_scopes.PermissionDenied` unless one hat allows ``action``."""
    decision = check_any(actors, action)
    if decision.denial is not None:
        raise PermissionDenied(decision.denial)


def check_object_any(
    actors: Iterable[Actor | str],
    action: Permission | str,
    obj: Any,
    principal: Any = None,
) -> Decision:
    """Decide whether any of ``actors`` may perform ``action`` on ``obj``.

    Actors are read in the order given and the first allowance answers, so an
    actor reaching everything never has to read the row. A slice that cannot be
    resolved — a principal missing the attribute it filters on, or a row missing
    the field it narrows — is held back while the other hats are tried, and
    raised only if none of them reaches the row.
    """
    furthest: Decision | None = None
    unresolved: LookupError | None = None
    for actor in actors:
        try:
            decision = check_object(actor, action, obj, principal)
        except (MissingObjectKey, MissingScopeKey) as error:
            if unresolved is None:
                unresolved = error
            continue
        if decision.allowed:
            return decision
        if furthest is None or _reach(decision) > _reach(furthest):
            furthest = decision
    if unresolved is not None:
        raise unresolved
    return _without_actors(action) if furthest is None else furthest


def owns_any(
    actors: Iterable[Actor | str],
    action: Permission | str,
    obj: Any,
    principal: Any = None,
) -> bool:
    """Tell whether ``obj`` is inside the slice any of ``actors`` reaches."""
    return check_object_any(actors, action, obj, principal).allowed


def require_object_any(
    actors: Iterable[Actor | str],
    action: Permission | str,
    obj: Any,
    principal: Any = None,
) -> None:
    """Raise :class:`~role_scopes.PermissionDenied` unless one hat reaches ``obj``."""
    decision = check_object_any(actors, action, obj, principal)
    if decision.denial is not None:
        raise PermissionDenied(decision.denial)


def scope_queryset_any(
    queryset: _QuerySetT,
    actors: Iterable[Actor | str],
    permission: Permission | str,
    principal: Any = None,
) -> _QuerySetT:
    """Narrow ``queryset`` to the rows any of ``actors`` may see.

    An actor without the capability, an actor the matrix does not know and a
    resource with no slice declared for an actor contribute nothing, so a stale
    role in the collection neither widens nor empties the result. One hat
    narrows exactly the way :func:`~role_scopes.scope_queryset` does; two or
    more are combined with ``OR`` and returned ``distinct()``, because a union
    across a relation can match the same row twice. An actor reaching
    everything answers for the whole collection, and otherwise a slice the
    principal cannot resolve raises :class:`~role_scopes.MissingScopeKey`
    rather than quietly dropping the rows it stood for.
    """
    union = Q()
    slices = 0
    unresolved: MissingScopeKey | None = None
    for actor in actors:
        if not check(actor, permission).allowed:
            continue
        scope = scope_for(actor, permission)
        if scope.kind is ScopeKind.EVERYTHING:
            return queryset
        if scope.kind is ScopeKind.NOTHING:
            continue
        try:
            filters = scope.filters(principal)
        except MissingScopeKey as error:
            if unresolved is None:
                unresolved = error
            continue
        union |= Q(**filters)
        slices += 1
    if unresolved is not None:
        raise unresolved
    if not slices:
        return queryset.none()
    if slices > 1:
        return queryset.filter(union).distinct()
    return queryset.filter(union)
