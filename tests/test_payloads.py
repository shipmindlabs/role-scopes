"""Write scoping: the slice read as a constraint on a row that does not exist.

The expectations are written against the shipped tables by hand — a customer
owns the orders carrying its ``customer_id``, warehouse the rows of its store,
support every row — so they do not come from the declaration under test. The
membership table is written out here, because the shipped one gives a warehouse
principal exactly one store.
"""

from __future__ import annotations

from typing import Any

import pytest

from role_scopes import (
    Actor,
    MissingScopeKey,
    Permission,
    PermissionDenied,
    Rule,
    Scope,
    UnstampableScope,
    check_payload,
    require_payload,
    scope_defaults,
    scope_payload,
)
from role_scopes import scopes as scopes_module

MULTI_STORE = {
    Actor.WAREHOUSE: {
        "inventory": Scope.owned(
            "inventory.own_stores",
            store_id__in="store_ids",
            sku_family="sku_family",
        ),
    }
}


class Principal:
    def __init__(self, **attributes: Any) -> None:
        for key, value in attributes.items():
            setattr(self, key, value)


@pytest.fixture
def multi_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scopes_module, "ACTOR_SCOPES", MULTI_STORE)


@pytest.fixture
def customer_without_slices(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scopes_module, "ACTOR_SCOPES", {Actor.CUSTOMER: {}})


def test_a_new_row_carries_the_values_of_the_slice() -> None:
    assert scope_defaults(
        "customer", Permission.ORDER_CREATE, Principal(customer_id=5)
    ) == {"customer_id": 5}
    assert scope_defaults(
        Actor.WAREHOUSE, Permission.INVENTORY_COUNT, Principal(store_id=3)
    ) == {"store_id": 3}


def test_an_actor_reaching_everything_constrains_no_field() -> None:
    assert scope_defaults(Actor.SUPPORT, Permission.TICKET_CREATE, Principal()) == {}
    assert scope_defaults(Actor.BACK_OFFICE, Permission.ORDER_CREATE, None) == {}


def test_a_resource_with_no_slice_names_no_value_a_new_row_could_carry(
    customer_without_slices: None,
) -> None:
    with pytest.raises(UnstampableScope) as raised:
        scope_defaults("customer", Permission.ORDER_CREATE, Principal(customer_id=5))
    assert "order" in str(raised.value)


def test_a_relation_path_is_not_a_field_of_the_new_row() -> None:
    with pytest.raises(UnstampableScope) as raised:
        scope_defaults("courier", Permission.ORDER_VIEW, Principal(courier_id=7))
    assert "shipment__courier_id" in str(raised.value)


def test_membership_does_not_say_which_value_a_new_row_carries(
    multi_store: None,
) -> None:
    with pytest.raises(UnstampableScope) as raised:
        scope_defaults(
            Actor.WAREHOUSE,
            Permission.INVENTORY_COUNT,
            Principal(store_ids=[3, 7], sku_family="ambient"),
        )
    assert "'store_id'" in str(raised.value)


def test_a_principal_missing_the_attribute_is_not_quietly_stamped() -> None:
    with pytest.raises(MissingScopeKey):
        scope_defaults("customer", Permission.ORDER_CREATE, Principal())


def test_a_payload_inside_the_slice_is_allowed() -> None:
    decision = check_payload(
        "customer",
        Permission.ORDER_CREATE,
        {"customer_id": 5, "total": "24.90"},
        Principal(customer_id=5),
    )
    assert decision.allowed
    assert decision.actor == "customer"
    assert decision.action == "order.create"


def test_a_payload_naming_a_foreign_value_is_denied() -> None:
    decision = check_payload(
        "customer", "order.create", {"customer_id": 9}, Principal(customer_id=5)
    )
    assert not decision
    assert decision.denial is not None
    assert decision.denial.rule is Rule.PAYLOAD_SCOPED
    assert decision.denial.reason == (
        "'customer_id' places this new order outside order.own_customer"
    )
    assert decision.denial.as_dict()["rule"] == "payload.scoped"
    assert str(decision.denial) == (
        "customer may not order.create: 'customer_id' places this new order "
        "outside order.own_customer [payload.scoped]"
    )


def test_a_field_the_payload_leaves_out_is_not_a_denial() -> None:
    assert check_payload(
        "customer", Permission.ORDER_CREATE, {"total": "24.90"}, Principal(customer_id=5)
    ).allowed


def test_the_capability_is_answered_before_the_payload_is_read() -> None:
    decision = check_payload("courier", "order.create", {"customer_id": 5}, Principal())
    assert decision.denial is not None
    assert decision.denial.rule is Rule.PERMISSION_GRANTED


def test_a_stale_role_is_a_denial_not_an_error() -> None:
    decision = check_payload("intern", "order.create", {}, None)
    assert decision.denial is not None
    assert decision.denial.rule is Rule.ACTOR_KNOWN


def test_a_resource_with_no_slice_refuses_the_write(
    customer_without_slices: None,
) -> None:
    decision = check_payload(
        "customer", Permission.ORDER_CREATE, {"customer_id": 5}, Principal(customer_id=5)
    )
    assert decision.denial is not None
    assert decision.denial.rule is Rule.PAYLOAD_SCOPED
    assert decision.denial.reason == "no order slice is declared for customer"


def test_require_payload_raises_the_denial_it_reports() -> None:
    principal = Principal(customer_id=5)
    require_payload("customer", Permission.ORDER_CREATE, {"customer_id": 5}, principal)
    with pytest.raises(PermissionDenied) as raised:
        require_payload(
            "customer", Permission.ORDER_CREATE, {"customer_id": 9}, principal
        )
    assert raised.value.denial == check_payload(
        "customer", Permission.ORDER_CREATE, {"customer_id": 9}, principal
    ).denial


def test_the_write_is_stamped_with_the_slice() -> None:
    payload = {"total": "24.90"}
    stamped = scope_payload(
        "customer", Permission.ORDER_CREATE, payload, Principal(customer_id=5)
    )
    assert stamped == {"total": "24.90", "customer_id": 5}
    assert payload == {"total": "24.90"}


def test_a_value_the_payload_already_carries_is_kept() -> None:
    assert scope_payload(
        "customer", Permission.ORDER_CREATE, {"customer_id": 5}, Principal(customer_id=5)
    ) == {"customer_id": 5}


def test_a_foreign_value_raises_rather_than_being_overwritten() -> None:
    with pytest.raises(PermissionDenied) as raised:
        scope_payload(
            "customer",
            Permission.ORDER_CREATE,
            {"customer_id": 9},
            Principal(customer_id=5),
        )
    assert raised.value.denial is not None
    assert raised.value.denial.rule is Rule.PAYLOAD_SCOPED


def test_an_actor_reaching_everything_passes_the_payload_through() -> None:
    assert scope_payload(
        Actor.SUPPORT, Permission.TICKET_CREATE, {"customer_id": 9}, Principal()
    ) == {"customer_id": 9}


def test_a_membership_slice_is_stamped_only_where_it_is_an_equality(
    multi_store: None,
) -> None:
    principal = Principal(store_ids=[3, 7], sku_family="ambient")
    assert scope_payload(
        Actor.WAREHOUSE, Permission.INVENTORY_COUNT, {"store_id": 7}, principal
    ) == {"store_id": 7, "sku_family": "ambient"}


def test_a_membership_slice_the_payload_does_not_name_is_refused(
    multi_store: None,
) -> None:
    principal = Principal(store_ids=[3, 7], sku_family="ambient")
    with pytest.raises(UnstampableScope):
        scope_payload(Actor.WAREHOUSE, Permission.INVENTORY_COUNT, {}, principal)


def test_a_store_outside_the_membership_cannot_be_written(multi_store: None) -> None:
    principal = Principal(store_ids=[3, 7], sku_family="ambient")
    decision = check_payload(
        Actor.WAREHOUSE, Permission.INVENTORY_COUNT, {"store_id": 9}, principal
    )
    assert decision.denial is not None
    assert decision.denial.reason == (
        "'store_id' places this new inventory outside inventory.own_stores"
    )
