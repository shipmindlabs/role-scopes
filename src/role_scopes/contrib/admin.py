"""Optional Django adapter: auth permissions and an admin scoped by actor.

The core declares actors, permissions and slices as data. This module is the
only place that speaks Django's own vocabulary: it names each declared
permission the way ``auth`` would, fills one group per actor, and gates a
``ModelAdmin`` so back-office, support and warehouse staff can share one admin
without sharing rows.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from django.contrib import admin
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Q, QuerySet
from django.http import HttpRequest

from role_scopes.actors import Actor, Permission, permissions_for
from role_scopes.checks import check
from role_scopes.ownership import check_object
from role_scopes.scopes import resource_of, scope_queryset

__all__ = [
    "DEFAULT_ACTIONS",
    "GROUP_PREFIX",
    "ScopedModelAdmin",
    "codename_for",
    "group_name",
    "model_permissions",
    "permission_labels",
    "sync_groups",
]

GROUP_PREFIX = "role_scopes"

DEFAULT_ACTIONS: frozenset[str] = frozenset({"add", "change", "delete", "view"})

# ``create`` is the matrix name for what Django calls ``add``; every other
# action already reads the same on both sides.
_ACTION_ALIASES: Mapping[str, str] = {"create": "add"}

_ADMIN_ACTIONS: tuple[str, ...] = ("view", "add", "change", "delete")

_ADMIN_DEFAULTS: Mapping[str, str] = {"view": "view", "add": "create"}


def _split(permission: Permission | str) -> tuple[str, str]:
    resource, action = Permission(permission).value.split(".", 1)
    return resource, action


def codename_for(permission: Permission | str) -> str:
    """Return the ``auth`` codename of a declared permission."""
    resource, action = _split(permission)
    return f"{_ACTION_ALIASES.get(action, action)}_{resource}"


def model_permissions(resource: str) -> list[tuple[str, str]]:
    """Return the ``Meta.permissions`` entries a resource needs.

    Django creates the add, change, delete and view permissions for every
    model, so only the domain actions of the matrix are listed here.
    """
    entries: list[tuple[str, str]] = []
    for permission in Permission:
        declared_resource, action = _split(permission)
        if declared_resource != resource:
            continue
        codename = codename_for(permission)
        if codename.split("_", 1)[0] in DEFAULT_ACTIONS:
            continue
        entries.append((codename, f"Can {action} {resource}"))
    return sorted(entries)


def permission_labels(
    actor: Actor | str, app_labels: Mapping[str, str]
) -> frozenset[str]:
    """Return the ``app_label.codename`` permissions granted to ``actor``.

    ``app_labels`` maps a resource to the app that models it. A resource
    missing from the mapping is skipped, so a project that keeps reports or
    users out of the admin does not have to name a model for them.
    """
    labels: set[str] = set()
    for permission in permissions_for(actor):
        app_label = app_labels.get(resource_of(permission))
        if app_label is None:
            continue
        labels.add(f"{app_label}.{codename_for(permission)}")
    return frozenset(labels)


def group_name(actor: Actor | str) -> str:
    """Return the name of the auth group standing for ``actor``."""
    return f"{GROUP_PREFIX}:{Actor(actor).value}"


def sync_groups(
    app_labels: Mapping[str, str],
    *,
    actors: Iterable[Actor | str] | None = None,
) -> dict[str, int]:
    """Give one auth group per actor exactly the permissions the matrix grants.

    Idempotent, so it can run from a data migration or a deploy step. The
    group's permissions are replaced rather than added to, which is what makes
    a capability removed from the matrix leave the group as well.
    """
    from django.contrib.auth.models import Group
    from django.contrib.auth.models import Permission as AuthPermission

    synced: dict[str, int] = {}
    for value in Actor if actors is None else actors:
        actor = Actor(value)
        labels = permission_labels(actor, app_labels)
        query = Q()
        for label in sorted(labels):
            app_label, codename = label.split(".", 1)
            query |= Q(content_type__app_label=app_label, codename=codename)
        granted = list(AuthPermission.objects.filter(query)) if labels else []
        group, _ = Group.objects.get_or_create(name=group_name(actor))
        group.permissions.set(granted)
        synced[group.name] = len(granted)
    return synced


class ScopedModelAdmin(admin.ModelAdmin):
    """A ``ModelAdmin`` that shows each actor only its declared slice.

    A subclass names the resource it models. The changelist is narrowed by the
    declared scope and every object action is decided by an ownership check, so
    the rows an actor cannot see in the list are the rows it cannot open.

    View and add fall back to ``<resource>.view`` and ``<resource>.create``.
    Change and delete have no fallback: the matrix names domain actions rather
    than CRUD, so the permission that stands for editing a row is declared per
    admin and an action left unmapped is refused.
    """

    resource: str = ""
    actor_attribute: str = "role"
    superuser_actor: Actor | None = Actor.BACK_OFFICE

    view_permission: Permission | str | None = None
    add_permission: Permission | str | None = None
    change_permission: Permission | str | None = None
    delete_permission: Permission | str | None = None

    def __init__(self, model: Any, admin_site: Any) -> None:
        declared = any(
            getattr(self, f"{action}_permission", None) for action in _ADMIN_ACTIONS
        )
        if not self.resource and not declared:
            raise ImproperlyConfigured(
                f"{type(self).__name__} must declare a resource "
                f"or a permission for the admin actions it allows"
            )
        super().__init__(model, admin_site)

    def actor_for(self, request: HttpRequest) -> Actor | None:
        """Return the actor acting in ``request``, or ``None`` when unknown.

        A superuser carrying no actor falls back to ``superuser_actor``; set it
        to ``None`` to hold superusers to the same declarations as everyone.
        """
        user = getattr(request, "user", None)
        try:
            return Actor(getattr(user, self.actor_attribute, None))
        except ValueError:
            if self.superuser_actor is not None and getattr(
                user, "is_superuser", False
            ):
                return self.superuser_actor
            return None

    def permission_for(self, action: str) -> Permission | None:
        """Return the permission gating an admin ``action``, if one is mapped."""
        declared = getattr(self, f"{action}_permission", None)
        if declared is not None:
            return Permission(declared)
        default = _ADMIN_DEFAULTS.get(action)
        if default is None:
            return None
        try:
            return Permission(f"{self.resource}.{default}")
        except ValueError:
            return None

    def _allowed(
        self, request: HttpRequest, action: str, obj: Any = None
    ) -> bool:
        permission = self.permission_for(action)
        actor = self.actor_for(request)
        if permission is None or actor is None:
            return False
        if obj is None:
            return check(actor, permission).allowed
        return check_object(actor, permission, obj, request.user).allowed

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        """Narrow the changelist to the slice this actor may reach."""
        queryset = super().get_queryset(request)
        permission = self.permission_for("view")
        actor = self.actor_for(request)
        if permission is None or actor is None:
            return queryset.none()
        return scope_queryset(queryset, actor, permission, request.user)

    def has_view_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        """Tell whether this actor may read the model, or this row of it."""
        return self._allowed(request, "view", obj)

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Tell whether this actor may create rows of the model."""
        return self._allowed(request, "add")

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        """Tell whether this actor may edit the model, or this row of it."""
        return self._allowed(request, "change", obj)

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        """Tell whether this actor may delete the model, or this row of it."""
        return self._allowed(request, "delete", obj)

    def has_module_permission(self, request: HttpRequest) -> bool:
        """Show the app on the admin index when any action is allowed."""
        return any(self._allowed(request, action) for action in _ADMIN_ACTIONS)
