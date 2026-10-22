"""Set-valued principals: a slice narrowed by membership rather than equality.

The membership table is written by hand here rather than read from the shipped
declarations, which give a warehouse principal exactly one store: the feature
has to hold for the slice a project writes, not for the policy this package
happens to ship.
"""

from __future__ import annotations

from typing import Any

import pytest

from role_scopes import (
    Actor,
    MissingObjectKey,
    MissingScopeKey,
    Permission,
    Rule,
    Scope,
    ScopeDeclarationError,
    ScopeKind,
    check_object,
    owns,
    scope_queryset,
)
from role_scopes import scopes as scopes_module

MULTI_STORE = {
    Actor.WAREHOUSE: {
        "order": Scope.owned("order.own_stores", store_id__in="store_ids"),
        "shipment": Scope.owned("shipment.own_stores", order__store_id__in="store_ids"),
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


class Row:
    def __init__(self, **fields: Any) -> None:
        for key, value in fields.items():
            setattr(self, key, value)


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


@pytest.fixture
def multi_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scopes_module, "ACTOR_SCOPES", MULTI_STORE)


def test_a_trailing_in_declares_membership() -> None:
    scope = Scope.owned("order.own_stores", store_id__in="store_ids")
    assert scope.kind is ScopeKind.OWN
    assert scope.lookups == (("store_id__in", "store_ids"),)


@pytest.mark.parametrize(
    "lookup",
    [
        "store_id__exact",
        "store_id__gte",
        "store_id__isnull",
        "store_id__range",
        "name__icontains",
    ],
)
def test_any_other_trailing_lookup_is_refused_at_declaration(lookup: str) -> None:
    with pytest.raises(ScopeDeclarationError) as raised:
        Scope.owned("order.own_stores", **{lookup: "store_ids"})
    assert isinstance(raised.value, ValueError)
    assert lookup in str(raised.value)


def test_a_relation_path_is_not_read_as_a_lookup() -> None:
    scope = Scope.owned("order.own_assignment", shipment__courier_id="courier_id")
    assert scope.lookups == (("shipment__courier_id", "courier_id"),)
    relation = Scope.owned("shipment.own_stores", order__store_id__in="store_ids")
    assert relation.lookups == (("order__store_id__in", "store_ids"),)


def test_membership_resolves_to_a_tuple_of_values() -> None:
    scope = Scope.owned("order.own_stores", store_id__in="store_ids")
    assert scope.filters(Principal(store_ids=[3, 7])) == {"store_id__in": (3, 7)}
    assert scope.filters({"store_ids": {5}}) == {"store_id__in": (5,)}


def test_an_empty_membership_is_a_principal_that_reaches_no_rows() -> None:
    scope = Scope.owned("order.own_stores", store_id__in="store_ids")
    assert scope.filters(Principal(store_ids=())) == {"store_id__in": ()}


def test_a_principal_without_the_collection_raises() -> None:
    scope = Scope.owned("order.own_stores", store_id__in="store_ids")
    with pytest.raises(MissingScopeKey):
        scope.filters(Principal())


def test_a_string_is_not_read_as_a_collection_of_values() -> None:
    scope = Scope.owned("order.own_stores", store_id__in="store_ids")
    with pytest.raises(MissingScopeKey) as raised:
        scope.filters(Principal(store_ids="37"))
    assert "store_ids" in str(raised.value)


def test_a_single_value_is_not_read_as_a_collection() -> None:
    scope = Scope.owned("order.own_stores", store_id__in="store_ids")
    with pytest.raises(MissingScopeKey):
        scope.filters(Principal(store_ids=7))


def test_the_queryset_filters_by_membership(multi_store: None) -> None:
    narrowed = scope_queryset(
        FakeQuerySet(),
        Actor.WAREHOUSE,
        Permission.ORDER_VIEW,
        Principal(store_ids=[3, 7]),
    )
    assert narrowed.filters == {"store_id__in": (3, 7)}


def test_a_principal_with_no_stores_narrows_to_no_rows(multi_store: None) -> None:
    narrowed = scope_queryset(
        FakeQuerySet(), Actor.WAREHOUSE, Permission.ORDER_VIEW, Principal(store_ids=[])
    )
    assert narrowed.filters == {"store_id__in": ()}


def test_check_object_tests_membership(multi_store: None) -> None:
    principal = Principal(store_ids=[3, 7])
    assert owns(Actor.WAREHOUSE, Permission.ORDER_VIEW, Row(store_id=7), principal)
    assert not owns(Actor.WAREHOUSE, Permission.ORDER_VIEW, Row(store_id=9), principal)


def test_a_principal_with_no_stores_reaches_no_row(multi_store: None) -> None:
    assert not owns(
        Actor.WAREHOUSE, Permission.ORDER_VIEW, Row(store_id=3), Principal(store_ids=())
    )


def test_a_row_outside_the_membership_names_the_slice(multi_store: None) -> None:
    decision = check_object(
        Actor.WAREHOUSE,
        Permission.ORDER_VIEW,
        Row(store_id=9),
        Principal(store_ids=[3]),
    )
    assert decision.denial is not None
    assert decision.denial.rule is Rule.OBJECT_OWNED
    assert decision.denial.reason == "this order is outside order.own_stores"


def test_the_object_side_asks_for_the_field_without_the_lookup(
    multi_store: None,
) -> None:
    with pytest.raises(MissingObjectKey) as raised:
        check_object(
            Actor.WAREHOUSE, Permission.ORDER_VIEW, Row(), Principal(store_ids=[3])
        )
    assert "'store_id'" in str(raised.value)


def test_a_relation_is_followed_before_membership_is_tested(multi_store: None) -> None:
    principal = Principal(store_ids=[3, 7])
    assert owns(
        Actor.WAREHOUSE, Permission.SHIPMENT_VIEW, Row(order=Row(store_id=3)), principal
    )
    assert not owns(
        Actor.WAREHOUSE, Permission.SHIPMENT_VIEW, Row(order=Row(store_id=4)), principal
    )


def test_equality_and_membership_mix_in_one_slice(multi_store: None) -> None:
    principal = Principal(store_ids=[3, 7], sku_family="ambient")
    assert owns(
        Actor.WAREHOUSE,
        Permission.INVENTORY_VIEW,
        Row(store_id=7, sku_family="ambient"),
        principal,
    )
    assert not owns(
        Actor.WAREHOUSE,
        Permission.INVENTORY_VIEW,
        Row(store_id=7, sku_family="frozen"),
        principal,
    )
    narrowed = scope_queryset(
        FakeQuerySet(), Actor.WAREHOUSE, Permission.INVENTORY_VIEW, principal
    )
    assert narrowed.filters == {"store_id__in": (3, 7), "sku_family": "ambient"}
