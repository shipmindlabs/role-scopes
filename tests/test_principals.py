"""Several actors read as one principal: the union of what each hat reaches.

The expectations are written against the shipped tables by hand — a courier
reaches the shipments assigned to it, warehouse the rows of its store, support
every row — so they do not come from the declaration under test. Nothing here
touches a database: the queryset is a stand-in recording the ``Q`` it was
narrowed by.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.db.models import Q

from role_scopes import (
    NO_ACTOR,
    Actor,
    MissingObjectKey,
    MissingScopeKey,
    Permission,
    PermissionDenied,
    Rule,
    Scope,
    check_any,
    check_object_any,
    owns_any,
    require_any,
    require_object_any,
    scope_queryset_any,
)
from role_scopes import scopes as scopes_module

BOTH_HATS = ("warehouse", "courier")


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
        self, query: Any = None, empty: bool = False, deduplicated: bool = False
    ) -> None:
        self.query = query
        self.empty = empty
        self.deduplicated = deduplicated

    def none(self) -> "FakeQuerySet":
        return FakeQuerySet(empty=True)

    def filter(self, *args: Any, **lookups: Any) -> "FakeQuerySet":
        return FakeQuerySet(query=args[0] if args else Q(**lookups))

    def distinct(self) -> "FakeQuerySet":
        return FakeQuerySet(query=self.query, deduplicated=True)


def supervisor() -> Principal:
    """A warehouse supervisor who also drives a van."""
    return Principal(store_id=3, courier_id=7)


def test_the_hat_that_allows_answers_for_the_principal() -> None:
    decision = check_any(["courier", "support"], Permission.SHIPMENT_REROUTE)
    assert decision.allowed
    assert decision.actor == "support"
    assert decision.action == "shipment.reroute"
    assert decision.denial is None


def test_the_first_hat_that_allows_is_the_one_reported() -> None:
    assert check_any(BOTH_HATS, Permission.SHIPMENT_VIEW).actor == "warehouse"
    assert check_any(reversed(BOTH_HATS), Permission.SHIPMENT_VIEW).actor == "courier"


def test_a_stale_role_beside_a_real_one_still_allows() -> None:
    assert check_any(iter(["intern", "courier"]), Permission.SHIPMENT_DELIVER).allowed


def test_a_principal_carrying_no_role_is_denied() -> None:
    decision = check_any([], Permission.ORDER_VIEW)
    assert not decision
    assert decision.action == "order.view"
    assert decision.denial is not None
    assert decision.denial.actor == NO_ACTOR
    assert decision.denial.rule is Rule.ACTOR_KNOWN
    assert decision.denial.reason == "no actor was given"


def test_a_stale_role_does_not_hide_why_the_real_one_was_refused() -> None:
    decision = check_any(["intern", "customer"], Permission.ORDER_REFUND)
    assert decision.denial is not None
    assert decision.denial.actor == "customer"
    assert decision.denial.rule is Rule.PERMISSION_GRANTED
    assert decision.denial.reason == "customer is not granted order.refund"


def test_nothing_but_stale_roles_is_denied_as_unknown() -> None:
    decision = check_any(["intern", "temp"], Permission.ORDER_VIEW)
    assert decision.denial is not None
    assert decision.denial.actor == "intern"
    assert decision.denial.rule is Rule.ACTOR_KNOWN


def test_an_unknown_action_is_reported_once_for_the_principal() -> None:
    decision = check_any(BOTH_HATS, "order.teleport")
    assert decision.denial is not None
    assert decision.denial.actor == "warehouse"
    assert decision.denial.rule is Rule.ACTION_KNOWN


def test_require_any_raises_the_denial_it_reports() -> None:
    actors = ["courier", "customer"]
    with pytest.raises(PermissionDenied) as raised:
        require_any(actors, Permission.ORDER_REFUND)
    assert raised.value.denial == check_any(actors, Permission.ORDER_REFUND).denial
    require_any(actors, Permission.ORDER_VIEW)


def test_either_hat_can_own_the_row() -> None:
    principal = supervisor()
    assert owns_any(
        BOTH_HATS,
        Permission.ORDER_VIEW,
        Row(store_id=3, shipment=Row(courier_id=12)),
        principal,
    )
    assert owns_any(
        BOTH_HATS,
        Permission.ORDER_VIEW,
        Row(store_id=9, shipment=Row(courier_id=7)),
        principal,
    )


def test_a_row_outside_every_slice_names_the_first_slice_tried() -> None:
    decision = check_object_any(
        BOTH_HATS,
        Permission.ORDER_VIEW,
        Row(store_id=9, shipment=Row(courier_id=12)),
        supervisor(),
    )
    assert decision.denial is not None
    assert decision.denial.actor == "warehouse"
    assert decision.denial.rule is Rule.OBJECT_OWNED
    assert decision.denial.reason == "this order is outside order.own_store"


def test_require_object_any_raises_for_a_row_no_hat_reaches() -> None:
    principal = supervisor()
    require_object_any(
        BOTH_HATS,
        Permission.ORDER_VIEW,
        Row(store_id=3, shipment=Row(courier_id=12)),
        principal,
    )
    with pytest.raises(PermissionDenied) as raised:
        require_object_any(
            BOTH_HATS,
            Permission.ORDER_VIEW,
            Row(store_id=9, shipment=Row(courier_id=12)),
            principal,
        )
    assert raised.value.denial is not None
    assert raised.value.denial.rule is Rule.OBJECT_OWNED


def test_a_hat_reaching_everything_never_reads_the_row() -> None:
    assert owns_any(["support", "courier"], Permission.ORDER_VIEW, Row(), Principal())
    assert owns_any(["courier", "support"], Permission.ORDER_VIEW, Row(), Principal())


def test_a_field_the_slice_narrows_on_is_still_required_of_the_row() -> None:
    with pytest.raises(MissingObjectKey):
        check_object_any(BOTH_HATS, Permission.ORDER_VIEW, Row(), supervisor())


def test_a_principal_missing_every_scope_key_is_not_quietly_denied() -> None:
    with pytest.raises(MissingScopeKey):
        check_object_any(
            BOTH_HATS,
            Permission.ORDER_VIEW,
            Row(store_id=3, shipment=Row(courier_id=7)),
            Principal(),
        )


def test_a_principal_carrying_no_role_reaches_no_row() -> None:
    decision = check_object_any(
        [], Permission.ORDER_VIEW, Row(store_id=3), supervisor()
    )
    assert decision.denial is not None
    assert decision.denial.actor == NO_ACTOR
    assert decision.denial.rule is Rule.ACTOR_KNOWN


def test_the_list_is_the_union_of_the_slices() -> None:
    narrowed = scope_queryset_any(
        FakeQuerySet(), BOTH_HATS, Permission.ORDER_VIEW, supervisor()
    )
    assert narrowed.query == (Q(store_id=3) | Q(shipment__courier_id=7))
    assert narrowed.deduplicated


def test_one_granted_hat_narrows_the_way_a_single_actor_does() -> None:
    narrowed = scope_queryset_any(
        FakeQuerySet(), ["courier", "intern"], Permission.SHIPMENT_VIEW, supervisor()
    )
    assert narrowed.query == Q(courier_id=7)
    assert not narrowed.deduplicated


def test_a_hat_reaching_everything_answers_for_the_whole_list() -> None:
    unscoped = FakeQuerySet()
    assert (
        scope_queryset_any(
            unscoped, ["courier", "support"], Permission.ORDER_VIEW, supervisor()
        )
        is unscoped
    )


def test_a_hat_reaching_everything_outweighs_an_unresolved_slice() -> None:
    unscoped = FakeQuerySet()
    assert (
        scope_queryset_any(
            unscoped, ["courier", "support"], Permission.ORDER_VIEW, Principal()
        )
        is unscoped
    )


def test_no_granted_hat_narrows_to_no_rows() -> None:
    assert scope_queryset_any(
        FakeQuerySet(),
        ["receiving", "intern"],
        Permission.ORDER_VIEW,
        Principal(store_id=3),
    ).empty
    assert scope_queryset_any(
        FakeQuerySet(), [], Permission.ORDER_VIEW, Principal()
    ).empty


def test_a_hat_with_no_declared_slice_adds_nothing_to_the_union(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        scopes_module,
        "ACTOR_SCOPES",
        {
            Actor.WAREHOUSE: {},
            Actor.COURIER: {
                "order": Scope.owned(
                    "order.own_assignment", shipment__courier_id="courier_id"
                )
            },
        },
    )
    narrowed = scope_queryset_any(
        FakeQuerySet(), BOTH_HATS, Permission.ORDER_VIEW, supervisor()
    )
    assert narrowed.query == Q(shipment__courier_id=7)
    assert not narrowed.deduplicated


def test_a_slice_the_principal_cannot_resolve_is_not_dropped() -> None:
    with pytest.raises(MissingScopeKey):
        scope_queryset_any(
            FakeQuerySet(), BOTH_HATS, Permission.ORDER_VIEW, Principal(store_id=3)
        )
