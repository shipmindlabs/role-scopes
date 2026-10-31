"""The admin adapter names declared permissions the way ``auth`` would.

The expected codenames and labels are written out by hand rather than read
back from the adapter: a name derived from the function under test would agree
with whatever that function happened to produce. Nothing here touches a
database, so the naming contract holds before any model exists.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from role_scopes import RESOURCES, Actor, Permission
from role_scopes.contrib.admin import (
    DEFAULT_ACTIONS,
    ScopedModelAdmin,
    codename_for,
    model_permissions,
    permission_labels,
)

APPS = {"order": "orders", "shipment": "orders", "inventory": "warehouse"}


def admin_for(**attributes: Any) -> ScopedModelAdmin:
    """Build a scoped admin without a model class or an admin site."""
    cls = type("ScopedOrderAdmin", (ScopedModelAdmin,), attributes)
    model = SimpleNamespace(
        _meta=SimpleNamespace(app_label="orders", model_name="order")
    )
    return cls(model, SimpleNamespace())


def test_the_four_django_defaults_are_the_ones_auth_creates() -> None:
    assert set(DEFAULT_ACTIONS) == {"add", "change", "delete", "view"}


@pytest.mark.parametrize(
    ("permission", "codename"),
    [
        (Permission.ORDER_CREATE, "add_order"),
        (Permission.RETURN_CREATE, "add_return"),
        (Permission.TICKET_CREATE, "add_ticket"),
        (Permission.ORDER_VIEW, "view_order"),
        (Permission.ORDER_CANCEL, "cancel_order"),
        (Permission.ORDER_REFUND, "refund_order"),
        (Permission.SHIPMENT_DELIVER, "deliver_shipment"),
        (Permission.SHIPMENT_REROUTE, "reroute_shipment"),
        (Permission.INVENTORY_ADJUST, "adjust_inventory"),
        (Permission.RECEIVING_ACCEPT, "accept_receiving"),
        (Permission.RETURN_APPROVE, "approve_return"),
        (Permission.USER_MANAGE, "manage_user"),
    ],
)
def test_create_becomes_add_and_every_other_action_reads_verbatim(
    permission: Permission, codename: str
) -> None:
    assert codename_for(permission) == codename


def test_a_permission_named_as_a_string_is_read_the_same() -> None:
    assert codename_for("order.create") == "add_order"
    assert codename_for("shipment.deliver") == "deliver_shipment"


def test_an_action_the_matrix_does_not_declare_is_an_error() -> None:
    with pytest.raises(ValueError):
        codename_for("order.teleport")


def test_a_model_carries_only_the_domain_actions() -> None:
    assert model_permissions("order") == [
        ("cancel_order", "Can cancel order"),
        ("refund_order", "Can refund order"),
    ]
    assert model_permissions("return") == [
        ("approve_return", "Can approve return"),
        ("inspect_return", "Can inspect return"),
    ]


def test_a_resource_of_pure_crud_needs_no_entries() -> None:
    assert model_permissions("report") == []


def test_a_resource_no_permission_names_has_nothing_to_declare() -> None:
    assert model_permissions("shipmnet") == []


@pytest.mark.parametrize("resource", sorted(RESOURCES))
def test_no_resource_restates_a_permission_django_already_creates(
    resource: str,
) -> None:
    for codename, label in model_permissions(resource):
        assert codename.split("_", 1)[0] not in DEFAULT_ACTIONS
        assert codename.endswith(f"_{resource}")
        assert label.startswith("Can ")
        assert label.endswith(f" {resource}")


def test_labels_are_app_qualified_codenames() -> None:
    assert permission_labels(Actor.COURIER, APPS) == frozenset(
        {
            "orders.view_order",
            "orders.view_shipment",
            "orders.pickup_shipment",
            "orders.deliver_shipment",
        }
    )


def test_a_resource_absent_from_the_app_map_is_skipped() -> None:
    assert permission_labels("courier", {"shipment": "orders"}) == frozenset(
        {
            "orders.view_shipment",
            "orders.pickup_shipment",
            "orders.deliver_shipment",
        }
    )


def test_an_empty_app_map_grants_nothing() -> None:
    assert permission_labels(Actor.COURIER, {}) == frozenset()


def test_the_mapped_resources_of_a_wider_actor_are_the_only_ones_named() -> None:
    labels = permission_labels(Actor.WAREHOUSE, APPS)
    assert labels == frozenset(
        {
            "orders.view_order",
            "orders.view_shipment",
            "orders.assign_shipment",
            "warehouse.view_inventory",
            "warehouse.count_inventory",
            "warehouse.adjust_inventory",
        }
    )
    assert not any(label.endswith("_return") for label in labels)


def test_view_and_add_fall_back_to_the_resource() -> None:
    admin = admin_for(resource="order")
    assert admin.permission_for("view") is Permission.ORDER_VIEW
    assert admin.permission_for("add") is Permission.ORDER_CREATE


def test_change_and_delete_have_no_fallback() -> None:
    admin = admin_for(resource="order")
    assert admin.permission_for("change") is None
    assert admin.permission_for("delete") is None


def test_a_declared_permission_gates_change_and_delete() -> None:
    admin = admin_for(
        resource="order",
        change_permission=Permission.ORDER_CANCEL,
        delete_permission="order.refund",
    )
    assert admin.permission_for("change") is Permission.ORDER_CANCEL
    assert admin.permission_for("delete") is Permission.ORDER_REFUND


def test_a_fallback_the_matrix_does_not_declare_is_not_invented() -> None:
    admin = admin_for(resource="report")
    assert admin.permission_for("view") is Permission.REPORT_VIEW
    assert admin.permission_for("add") is None


def test_an_action_outside_the_admin_four_is_unmapped() -> None:
    admin = admin_for(resource="order")
    assert admin.permission_for("escalate") is None
