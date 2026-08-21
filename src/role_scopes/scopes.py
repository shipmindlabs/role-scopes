"""Queryset scoping: the slice of a resource an actor is allowed to see.

The slice is declared here as data, keyed by actor and by the resource half of
a permission name: a courier reaches the shipments assigned to them, a
warehouse operator the store they work in. Because the key is the resource,
``shipment.view`` and ``shipment.deliver`` narrow the same way, and a view asks
for the slice instead of restating the filter.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, TypeVar

from django.db.models import QuerySet

from role_scopes.actors import Actor, Permission
from role_scopes.checks import check

__all__ = [
    "ACTOR_SCOPES",
    "RESOURCES",
    "MissingScopeKey",
    "Scope",
    "ScopeKind",
    "resource_of",
    "scope_for",
    "scope_queryset",
]

_QuerySetT = TypeVar("_QuerySetT", bound=QuerySet)


class MissingScopeKey(LookupError):
    """The principal lacks an attribute a declared scope filters on."""


class ScopeKind(str, Enum):
    """How wide an actor's slice of a resource is."""

    EVERYTHING = "everything"
    OWN = "own"
    NOTHING = "nothing"


@dataclass(frozen=True)
class Scope:
    """The rows of a resource an actor may reach.

    ``lookups`` pairs a queryset lookup with the attribute of the principal that
    fills it, so the declaration stays readable next to the permission and the
    resolved filter can be logged.
    """

    kind: ScopeKind
    label: str
    lookups: tuple[tuple[str, str], ...] = ()

    EVERYTHING: ClassVar[Scope]
    NOTHING: ClassVar[Scope]

    @classmethod
    def owned(cls, label: str, **lookups: str) -> Scope:
        """Declare a slice narrowed by attributes of the acting principal."""
        return cls(ScopeKind.OWN, label, tuple(lookups.items()))

    def filters(self, principal: Any) -> dict[str, Any]:
        """Resolve the declared lookups against ``principal``."""
        resolved: dict[str, Any] = {}
        for lookup, attribute in self.lookups:
            value = _principal_value(principal, attribute)
            if value is None:
                raise MissingScopeKey(
                    f"scope {self.label!r} needs {attribute!r} on the principal"
                )
            resolved[lookup] = value
        return resolved

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
