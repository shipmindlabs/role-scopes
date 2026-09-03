"""Optional DRF adapter: permission classes built from the declarations.

The core declares actors, permissions and slices as data. This module turns a
declaration into what a REST Framework view expects: one ``BasePermission``
that answers both the route question and the object question, and a mixin that
narrows the queryset by the same slice. An endpoint keeps its serializers and
stops hand-rolling role checks, and the 403 body carries the denial the logs
carry.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from types import MappingProxyType
from typing import Any

from django.db.models import QuerySet
from rest_framework.permissions import BasePermission
from rest_framework.request import Request

from role_scopes.actors import Actor, Permission
from role_scopes.checks import Decision, Denial, Rule, check
from role_scopes.ownership import check_object
from role_scopes.scopes import RESOURCES, scope_queryset

__all__ = [
    "ANONYMOUS",
    "METHOD_ACTIONS",
    "VIEWSET_ACTIONS",
    "ScopedPermission",
    "ScopedQuerysetMixin",
    "scoped_permission",
]

ANONYMOUS = "anonymous"

# What a plain ``APIView`` is doing, named the way the matrix names it.
METHOD_ACTIONS: Mapping[str, str] = MappingProxyType(
    {"GET": "view", "HEAD": "view", "OPTIONS": "view", "POST": "create"}
)

# The viewset actions that carry an obvious matrix name. ``update``, ``destroy``
# and custom actions are absent on purpose: the matrix names domain actions
# rather than CRUD, so they are declared per view or refused.
VIEWSET_ACTIONS: Mapping[str, str] = MappingProxyType(
    {"list": "view", "retrieve": "view", "create": "create"}
)


def _label(value: object) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


class ScopedPermission(BasePermission):
    """A DRF permission that reads the matrix instead of restating it.

    The actor is read from ``request.user.role`` (``actor_attribute`` renames
    it). ``actions`` maps a viewset action or an HTTP method to a declared
    permission; ``list``, ``retrieve`` and ``create`` fall back to
    ``<resource>.view`` and ``<resource>.create``, and anything left unmapped
    is refused rather than guessed.

    Both questions are answered here: DRF asks :meth:`has_permission` on every
    request and :meth:`has_object_permission` on the detail routes that call
    ``get_object()``, so the row a list hides is the row a detail refuses.
    """

    resource: str = ""
    actor_attribute: str = "role"
    actions: Mapping[str, Permission] = MappingProxyType({})

    denial: Denial | None = None
    message: Any = None

    def actor_for(self, request: Request) -> Actor | str | None:
        """Return the actor carried by ``request``, or ``None`` when it has none."""
        user = getattr(request, "user", None)
        return getattr(user, self.actor_attribute, None) or None

    def requested(self, request: Request, view: Any) -> str:
        """Return what the route was asked to do, for the denial to name."""
        action = getattr(view, "action", None)
        if action:
            return str(action)
        return str(getattr(request, "method", "") or "").upper()

    def permission_for(self, request: Request, view: Any) -> Permission | None:
        """Return the declared permission gating this request, if one is mapped."""
        method = str(getattr(request, "method", "") or "").upper()
        action = getattr(view, "action", None)
        for key in (action, method):
            if key and key in self.actions:
                return self.actions[key]
        # A viewset names what it is doing, so a custom action never inherits
        # the fallback of the method it happens to use.
        default = VIEWSET_ACTIONS.get(action) if action else METHOD_ACTIONS.get(method)
        if default is None or not self.resource:
            return None
        try:
            return Permission(f"{self.resource}.{default}")
        except ValueError:
            return None

    def _deny(self, actor: str, action: str, rule: Rule, reason: str) -> bool:
        denial = Denial(actor, action, rule, reason)
        self.denial = denial
        self.message = denial.as_dict()
        return False

    def _decide(self, decision: Decision) -> bool:
        self.denial = decision.denial
        self.message = None if decision.denial is None else decision.denial.as_dict()
        return decision.allowed

    def _gate(self, request: Request, view: Any) -> Permission | bool:
        actor = self.actor_for(request)
        permission = self.permission_for(request, view)
        if permission is None:
            requested = self.requested(request, view)
            return self._deny(
                _label(actor) if actor is not None else ANONYMOUS,
                requested,
                Rule.ACTION_KNOWN,
                f"no permission is mapped for {requested!r}",
            )
        if actor is None:
            return self._deny(
                ANONYMOUS,
                permission.value,
                Rule.ACTOR_KNOWN,
                "the request carries no actor",
            )
        return permission

    def has_permission(self, request: Request, view: Any) -> bool:
        """Tell whether this actor may reach the route at all."""
        gated = self._gate(request, view)
        if gated is False:
            return False
        assert isinstance(gated, Permission)
        return self._decide(check(self.actor_for(request), gated))

    def has_object_permission(self, request: Request, view: Any, obj: Any) -> bool:
        """Tell whether this row is inside the slice the actor reaches."""
        gated = self._gate(request, view)
        if gated is False:
            return False
        assert isinstance(gated, Permission)
        return self._decide(
            check_object(
                self.actor_for(request), gated, obj, getattr(request, "user", None)
            )
        )

    def scoped_queryset(
        self, queryset: QuerySet, request: Request, view: Any
    ) -> QuerySet:
        """Narrow ``queryset`` to the rows this request may reach."""
        actor = self.actor_for(request)
        permission = self.permission_for(request, view)
        if actor is None or permission is None:
            return queryset.none()
        return scope_queryset(
            queryset, actor, permission, getattr(request, "user", None)
        )


class ScopedQuerysetMixin:
    """Narrow a generic view's queryset by the slice its permission declares.

    Mixed in before the DRF view class, so the list a client reads and the
    object it may open come from one declaration.
    """

    def get_queryset(self) -> QuerySet:
        """Return the view's queryset, narrowed to the actor's slice."""
        queryset = super().get_queryset()  # type: ignore[misc]
        for permission in self.get_permissions():  # type: ignore[attr-defined]
            if isinstance(permission, ScopedPermission):
                return permission.scoped_queryset(queryset, self.request, self)  # type: ignore[attr-defined]
        return queryset


def scoped_permission(
    resource: str,
    actions: Mapping[str, Permission | str] | None = None,
    *,
    name: str | None = None,
    actor_attribute: str = "role",
) -> type[ScopedPermission]:
    """Build the permission class a view over ``resource`` needs.

    ``actions`` is keyed by viewset action or HTTP method. Both the resource
    and every permission named are resolved here, so a route mapped to a
    capability the matrix does not declare fails at import time rather than on
    the first request that reaches it.
    """
    if resource not in RESOURCES:
        raise ValueError(f"{resource!r} is not a declared resource")

    declared = MappingProxyType(
        {key: Permission(value) for key, value in (actions or {}).items()}
    )
    class_name = name or f"{resource.replace('_', ' ').title().replace(' ', '')}Access"
    return type(
        class_name,
        (ScopedPermission,),
        {
            "resource": resource,
            "actions": declared,
            "actor_attribute": actor_attribute,
        },
    )
