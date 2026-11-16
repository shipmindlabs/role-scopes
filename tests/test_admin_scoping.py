"""The admin adapter under failure: who it refuses and which rows it hides.

Nothing here touches a database. The model is a stand-in carrying the two
attributes ``ModelAdmin`` reads and a manager handing back a recording
queryset, so the gating and the narrowing are observed without migrations. The
expectations are written against the shipped tables by hand rather than read
back from them, except where a slice the package does not ship is needed, and
that one is declared in the test.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from role_scopes import (
    Actor,
    MissingObjectKey,
    MissingScopeKey,
    Permission,
)
from role_scopes import scopes as scopes_module
from role_scopes.contrib.admin import GROUP_PREFIX, ScopedModelAdmin, group_name


class FakeQuerySet:
    def __init__(
        self, filters: dict[str, Any] | None = None, empty: bool = False
    ) -> None:
        self.filters = filters
        self.empty = empty

    def none(self) -> "FakeQuerySet":
        return FakeQuerySet(empty=True)

    def filter(self, **lookups: Any) -> "FakeQuerySet":
        return FakeQuerySet(filters=lookups)


class Principal:
    def __init__(self, **attributes: Any) -> None:
        self.is_superuser = False
        for key, value in attributes.items():
            setattr(self, key, value)


class Row:
    def __init__(self, **fields: Any) -> None:
        for key, value in fields.items():
            setattr(self, key, value)


def admin_for(**attributes: Any) -> ScopedModelAdmin:
    """Build a scoped admin over a stand-in model and a recording manager."""
    cls = type("ScopedOrderAdmin", (ScopedModelAdmin,), attributes)
    unscoped = FakeQuerySet()
    model = SimpleNamespace(
        _meta=SimpleNamespace(app_label="orders", model_name="order"),
        _default_manager=SimpleNamespace(get_queryset=lambda: unscoped),
    )
    instance = cls(model, SimpleNamespace())
    instance.unscoped = unscoped  # type: ignore[attr-defined]
    return instance


def request_for(**attributes: Any) -> SimpleNamespace:
    return SimpleNamespace(user=Principal(**attributes))


def test_the_actor_is_read_from_the_user() -> None:
    admin = admin_for(resource="order")
    assert admin.actor_for(request_for(role="warehouse", store_id=3)) is Actor.WAREHOUSE


def test_the_attribute_carrying_the_actor_can_be_renamed() -> None:
    admin = admin_for(resource="order", actor_attribute="actor_kind")
    assert admin.actor_for(request_for(actor_kind="support")) is Actor.SUPPORT
    assert admin.actor_for(request_for(role="support")) is None


def test_a_stale_role_is_refused_rather_than_raised() -> None:
    admin = admin_for(resource="order")
    request = request_for(role="intern", store_id=3)
    assert admin.actor_for(request) is None
    assert admin.has_view_permission(request) is False
    assert admin.has_module_permission(request) is False
    assert admin.get_queryset(request).empty


def test_a_superuser_without_an_actor_is_treated_as_back_office() -> None:
    admin = admin_for(resource="order")
    request = request_for(is_superuser=True)
    assert admin.actor_for(request) is Actor.BACK_OFFICE
    assert admin.has_view_permission(request) is True
    assert admin.get_queryset(request) is admin.unscoped  # type: ignore[attr-defined]


def test_a_superuser_carrying_an_actor_keeps_it() -> None:
    admin = admin_for(resource="order", change_permission=Permission.ORDER_CANCEL)
    request = request_for(role="warehouse", store_id=3, is_superuser=True)
    assert admin.actor_for(request) is Actor.WAREHOUSE
    assert admin.has_change_permission(request) is False


def test_superusers_can_be_held_to_the_declarations() -> None:
    admin = admin_for(resource="order", superuser_actor=None)
    request = request_for(is_superuser=True)
    assert admin.actor_for(request) is None
    assert admin.has_view_permission(request) is False
    assert admin.get_queryset(request).empty


def test_an_actor_without_the_capability_sees_no_module_at_all() -> None:
    admin = admin_for(resource="inventory")
    request = request_for(role="customer", customer_id=4)
    assert admin.has_view_permission(request) is False
    assert admin.has_add_permission(request) is False
    assert admin.has_module_permission(request) is False


def test_change_and_delete_stay_refused_until_they_are_declared() -> None:
    admin = admin_for(resource="order")
    request = request_for(role="back_office")
    assert admin.has_view_permission(request) is True
    assert admin.has_add_permission(request) is True
    assert admin.has_change_permission(request) is False
    assert admin.has_delete_permission(request) is False


def test_a_declared_change_permission_is_answered_from_the_matrix() -> None:
    admin = admin_for(resource="order", change_permission=Permission.ORDER_CANCEL)
    assert admin.has_change_permission(request_for(role="support")) is True
    assert (
        admin.has_change_permission(request_for(role="warehouse", store_id=3)) is False
    )


def test_a_permission_the_matrix_does_not_declare_raises_when_consulted() -> None:
    admin = admin_for(resource="order", change_permission="order.teleport")
    with pytest.raises(ValueError):
        admin.has_change_permission(request_for(role="back_office"))


def test_an_admin_declaring_neither_a_resource_nor_a_permission_is_refused() -> None:
    with pytest.raises(ImproperlyConfigured) as raised:
        admin_for()
    assert "ScopedOrderAdmin" in str(raised.value)


def test_an_admin_may_declare_a_permission_instead_of_a_resource() -> None:
    admin = admin_for(change_permission=Permission.ORDER_CANCEL)
    request = request_for(role="back_office")
    assert admin.permission_for("change") is Permission.ORDER_CANCEL
    assert admin.permission_for("view") is None
    assert admin.has_change_permission(request) is True
    assert admin.has_view_permission(request) is False
    assert admin.get_queryset(request).empty


def test_the_changelist_is_narrowed_by_the_declared_slice() -> None:
    admin = admin_for(resource="order")
    request = request_for(role="warehouse", store_id=3)
    assert admin.get_queryset(request).filters == {"store_id": 3}


def test_an_actor_reaching_everything_reads_the_changelist_unchanged() -> None:
    admin = admin_for(resource="order")
    request = request_for(role="support")
    assert admin.get_queryset(request) is admin.unscoped  # type: ignore[attr-defined]


def test_a_principal_missing_the_scope_key_is_not_quietly_widened() -> None:
    admin = admin_for(resource="order")
    request = request_for(role="warehouse")
    with pytest.raises(MissingScopeKey):
        admin.get_queryset(request)
    with pytest.raises(MissingScopeKey):
        admin.has_view_permission(request, Row(store_id=3))


def test_a_row_outside_the_slice_cannot_be_opened() -> None:
    admin = admin_for(resource="order")
    request = request_for(role="warehouse", store_id=3)
    assert admin.has_view_permission(request, Row(store_id=3)) is True
    assert admin.has_view_permission(request, Row(store_id=9)) is False


def test_an_actor_reaching_everything_opens_every_row() -> None:
    admin = admin_for(resource="order")
    request = request_for(role="support")
    assert admin.has_view_permission(request, Row(store_id=9)) is True


def test_delete_is_decided_on_the_row_as_well_as_the_model() -> None:
    admin = admin_for(resource="return", delete_permission=Permission.RETURN_INSPECT)
    request = request_for(role="warehouse", store_id=3)
    assert admin.has_delete_permission(request) is True
    assert admin.has_delete_permission(request, Row(store_id=3)) is True
    assert admin.has_delete_permission(request, Row(store_id=9)) is False


def test_a_row_missing_the_field_the_slice_narrows_on_raises() -> None:
    admin = admin_for(resource="order")
    request = request_for(role="warehouse", store_id=3)
    with pytest.raises(MissingObjectKey):
        admin.has_view_permission(request, Row())


def test_a_relation_is_followed_the_way_the_changelist_joins_it() -> None:
    admin = admin_for(resource="order")
    request = request_for(role="courier", courier_id=7)
    assert admin.has_view_permission(request, Row(shipment=Row(courier_id=7))) is True
    assert admin.has_view_permission(request, Row(shipment=Row(courier_id=12))) is False


def test_a_resource_with_no_slice_shows_the_model_and_refuses_every_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scopes_module, "ACTOR_SCOPES", {Actor.WAREHOUSE: {}})
    admin = admin_for(resource="order")
    request = request_for(role="warehouse", store_id=3)
    assert admin.has_view_permission(request) is True
    assert admin.get_queryset(request).empty
    assert admin.has_view_permission(request, Row(store_id=3)) is False


def test_the_module_is_shown_as_soon_as_one_action_is_allowed() -> None:
    admin = admin_for(resource="order")
    assert admin.has_module_permission(request_for(role="customer", customer_id=4)) is (
        True
    )
    assert (
        admin.has_module_permission(request_for(role="receiving", store_id=3)) is False
    )


def test_add_is_decided_without_a_row() -> None:
    admin = admin_for(resource="order")
    assert admin.has_add_permission(request_for(role="customer", customer_id=4)) is True
    assert admin.has_add_permission(request_for(role="warehouse", store_id=3)) is False


def test_a_group_is_named_after_the_actor() -> None:
    assert group_name(Actor.COURIER) == f"{GROUP_PREFIX}:courier"
    assert group_name("back_office") == f"{GROUP_PREFIX}:back_office"


def test_an_actor_the_matrix_does_not_know_has_no_group() -> None:
    with pytest.raises(ValueError):
        group_name("intern")
