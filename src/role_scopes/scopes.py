"""Queryset scoping: the slice of a resource an actor is allowed to see.

The slice is declared here as data, keyed by actor and by the resource half of
a permission name: a courier reaches the shipments assigned to them, a
warehouse operator the store they work in. Because the key is the resource,
``shipment.view`` and ``shipment.deliver`` narrow the same way, and a view asks
for the slice instead of restating the filter.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, TypeVar

from django.db.models import QuerySet

from role_scopes.actors import Actor, Permission
from role_scopes.checks import check

__all__ = [
    "ACTOR_SCOPES",
    "MEMBERSHIP_LOOKUP",
    "QUERY_LOOKUPS",
    "RESOURCES",
    "MissingScopeKey",
    "Scope",
    "ScopeDeclarationError",
    "ScopeKind",
    "resource_of",
    "scope_for",
    "scope_queryset",
    "split_lookup",
]

_QuerySetT = TypeVar("_QuerySetT", bound=QuerySet)


class MissingScopeKey(LookupError):
    """The principal lacks a value a declared scope filters on."""


class ScopeDeclarationError(ValueError):
    """A declared slice names a lookup an ownership check cannot answer."""


class ScopeKind(str, Enum):
    """How wide an actor's slice of a resource is."""

    EVERYTHING = "everything"
    OWN = "own"
    NOTHING = "nothing"


# Trailing segments Django reads as a lookup rather than as a field name.
QUERY_LOOKUPS: frozenset[str] = frozenset(
    {
        "exact",
        "iexact",
        "in",
        "gt",
        "gte",
        "lt",
        "lte",
        "range",
        "isnull",
        "contains",
        "icontains",
        "startswith",
        "istartswith",
        "endswith",
        "iendswith",
        "regex",
        "iregex",
        "overlap",
        "contained_by",
        "has_key",
        "has_keys",
        "has_any_keys",
    }
)

MEMBERSHIP_LOOKUP = "in"


def split_lookup(lookup: str) -> tuple[str, str | None]:
    """Split a declared lookup into its field path and trailing lookup name.

    ``store_id__in`` reads as the field ``store_id`` narrowed by membership,
    while ``shipment__courier_id`` is a relation path carrying no lookup of its
    own.
    """
    path, _, last = lookup.rpartition("__")
    if path and last in QUERY_LOOKUPS:
        return path, last
    return lookup, None


@dataclass(frozen=True)
class Scope:
    """The rows of a resource an actor may reach.

    ``lookups`` pairs a queryset lookup with the attribute of the principal that
    fills it, so the declaration stays readable next to the permission and the
    resolved filter can be logged. A lookup ending in ``__in`` is read as
    membership: the principal carries several values and every row carrying one
    of them is theirs.
    """

    kind: ScopeKind
    label: str
    lookups: tuple[tuple[str, str], ...] = ()

    EVERYTHING: ClassVar[Scope]
    NOTHING: ClassVar[Scope]

    @classmethod
    def owned(cls, label: str, **lookups: str) -> Scope:
        """Declare a slice narrowed by attributes of the acting principal.

        A lookup is a field path compared for equality, or a path with a
        trailing ``in`` for a principal that reaches several of its values. Any
        other trailing lookup raises :class:`ScopeDeclarationError` here: a
        queryset could narrow by it, but ``check_object()`` would have no way of
        answering the same question about a single row.
        """
        for lookup in lookups:
            _, trailing = split_lookup(lookup)
            if trailing is not None and trailing != MEMBERSHIP_LOOKUP:
                raise ScopeDeclarationError(
                    f"scope {label!r} declares {lookup!r}, and {trailing!r} is "
                    f"not a lookup a slice may end with: narrow by equality or "
                    f"by membership ({MEMBERSHIP_LOOKUP!r})"
                )
        return cls(ScopeKind.OWN, label, tuple(lookups.items()))

    def filters(self, principal: Any) -> dict[str, Any]:
        """Resolve the declared lookups against ``principal``.

        A membership lookup resolves to a tuple, so the same values narrow a
        queryset and answer an object check. An empty one is a principal that
        reaches no rows, which is not the same answer as a missing attribute.
        """
        resolved: dict[str, Any] = {}
        for lookup, attribute in self.lookups:
            value = _principal_value(principal, attribute)
            if value is None:
                raise MissingScopeKey(
                    f"scope {self.label!r} needs {attribute!r} on the principal"
                )
            _, trailing = split_lookup(lookup)
            if trailing == MEMBERSHIP_LOOKUP:
                value = self._membership(attribute, value)
            resolved[lookup] = value
        return resolved

    def _membership(self, attribute: str, value: Any) -> tuple[Any, ...]:
        # A string is iterable, and reading one as a collection of characters
        # would widen the slice to every row sharing a character with it.
        if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
            raise MissingScopeKey(
                f"scope {self.label!r} needs {attribute!r} on the principal to be "
                f"a collection of values, not {type(value).__name__}"
            )
        return tuple(value)

    def __str__(self) -> str:
        return self.label


Scope.EVERYTHING = Scope(ScopeKind.EVERYTHING, "everything")
Scope.NOTHING = Scope(ScopeKind.NOTHING, "nothing")


def _principal_value(principal: Any, attribute: str) -> Any:
    if isinstance(principal, Mapping):
        return principal.get(attribute)
    return getattr(principal, attribute, None)


RESOURCES: frozenset[str] = frozenset(
    permission.value.split(".", 1)[0] for permission in Permission
)


ACTOR_SCOPES: Mapping[Actor, Mapping[str, Scope]] = MappingProxyType(
    {
        Actor.CUSTOMER: MappingProxyType(
            {
                "order": Scope.owned("order.own_customer", customer_id="customer_id"),
                "shipment": Scope.owned(
                    "shipment.own_customer", order__customer_id="customer_id"
                ),
                "return": Scope.owned(
                    "return.own_customer", order__customer_id="customer_id"
                ),
                "ticket": Scope.owned("ticket.own_customer", customer_id="customer_id"),
            }
        ),
        Actor.COURIER: MappingProxyType(
            {
                "order": Scope.owned(
                    "order.own_assignment", shipment__courier_id="courier_id"
                ),
                "shipment": Scope.owned(
                    "shipment.own_assignment", courier_id="courier_id"
                ),
            }
        ),
        Actor.WAREHOUSE: MappingProxyType(
            {
                "order": Scope.owned("order.own_store", store_id="store_id"),
                "shipment": Scope.owned("shipment.own_store", store_id="store_id"),
                "inventory": Scope.owned("inventory.own_store", store_id="store_id"),
                "return": Scope.owned("return.own_store", store_id="store_id"),
            }
        ),
        Actor.RECEIVING: MappingProxyType(
            {
                "receiving": Scope.owned("receiving.own_store", store_id="store_id"),
                "inventory": Scope.owned("inventory.own_store", store_id="store_id"),
            }
        ),
        Actor.SUPPORT: MappingProxyType(
            {
                "order": Scope.EVERYTHING,
                "shipment": Scope.EVERYTHING,
                "return": Scope.EVERYTHING,
                "ticket": Scope.EVERYTHING,
                "user": Scope.EVERYTHING,
            }
        ),
        # Back-office runs the business and reads every row of every resource.
        Actor.BACK_OFFICE: MappingProxyType(
            {resource: Scope.EVERYTHING for resource in sorted(RESOURCES)}
        ),
    }
)


def resource_of(permission: Permission | str) -> str:
    """Return the resource half of a ``<resource>.<action>`` permission."""
    return Permission(permission).value.split(".", 1)[0]


def scope_for(actor: Actor | str, permission: Permission | str) -> Scope:
    """Return the slice ``actor`` may reach for the resource of ``permission``.

    A resource with no declared slice for this actor yields ``Scope.NOTHING``:
    visibility is granted, never assumed.
    """
    declared = ACTOR_SCOPES[Actor(actor)]
    return declared.get(resource_of(permission), Scope.NOTHING)


def scope_queryset(
    queryset: _QuerySetT,
    actor: Actor | str,
    permission: Permission | str,
    principal: Any = None,
) -> _QuerySetT:
    """Narrow ``queryset`` to the rows ``principal`` may see as ``actor``.

    The permission is checked first: an actor without the capability gets an
    empty queryset rather than a narrowed one. Raises :class:`MissingScopeKey`
    when the declared slice needs an attribute the principal does not carry.
    """
    if not check(actor, permission).allowed:
        return queryset.none()

    scope = scope_for(actor, permission)
    if scope.kind is ScopeKind.EVERYTHING:
        return queryset
    if scope.kind is ScopeKind.NOTHING:
        return queryset.none()
    return queryset.filter(**scope.filters(principal))
