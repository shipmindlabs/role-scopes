"""The DRF adapter answers from the matrix, the slice and nothing else."""

from __future__ import annotations

from typing import Any

import pytest

from role_scopes import Permission, Rule

pytest.importorskip("rest_framework")

from role_scopes.contrib.rest_framework import (  # noqa: E402
    ScopedQuerysetMixin,
    scoped_permission,
)

ShipmentAccess = scoped_permission(
    "shipment",
    {
        "deliver": Permission.SHIPMENT_DELIVER,
        "assign": Permission.SHIPMENT_ASSIGN,
    },
)


class Principal:
    def __init__(self, role: str | None = None, **attributes: Any) -> None:
        self.role = role
        for key, value in attributes.items():
            setattr(self, key, value)


class Request:
    def __init__(self, method: str = "GET", user: Any = None) -> None:
        self.method = method
        self.user = user


class View:
    def __init__(self, action: str | None = None) -> None:
        self.action = action


class Shipment:
    def __init__(self, courier_id: int) -> None:
        self.courier_id = courier_id


class FakeQuerySet:
    def __init__(self, filters: dict[str, Any] | None = None, empty: bool = False):
        self.filters = filters
        self.empty = empty

    def none(self) -> "FakeQuerySet":
        return FakeQuerySet(empty=True)

    def filter(self, **lookups: Any) -> "FakeQuerySet":
        return FakeQuerySet(filters=lookups)


class BaseView:
    def __init__(self, request: Request, action: str | None = None) -> None:
        self.request = request
        self.action = action
        self.queryset = FakeQuerySet()

    def get_permissions(self) -> list[Any]:
        return [ShipmentAccess()]

    def get_queryset(self) -> FakeQuerySet:
        return self.queryset


class ShipmentView(ScopedQuerysetMixin, BaseView):
    pass


def courier(courier_id: int = 7) -> Principal:
    return Principal(role="courier", courier_id=courier_id)


def test_list_falls_back_to_the_view_permission() -> None:
    permission = ShipmentAccess()
    assert permission.has_permission(Request(user=courier()), View("list"))


def test_declared_action_is_read_from_the_matrix() -> None:
    permission = ShipmentAccess()
    request = Request("POST", courier())
    assert permission.has_permission(request, View("deliver"))


def test_action_the_actor_lacks_is_denied_with_its_rule() -> None:
    permission = ShipmentAccess()
    assert not permission.has_permission(Request("POST", courier()), View("assign"))
    assert permission.denial is not None
    assert permission.denial.rule is Rule.PERMISSION_GRANTED
    assert permission.message == permission.denial.as_dict()


def test_unmapped_action_is_refused_rather_than_guessed() -> None:
    permission = ShipmentAccess()
    assert not permission.has_permission(Request("DELETE", courier()), View("destroy"))
    assert permission.denial is not None
    assert permission.denial.rule is Rule.ACTION_KNOWN
    assert permission.denial.action == "destroy"


def test_custom_post_action_does_not_inherit_create() -> None:
    orders = scoped_permission("order")
    permission = orders()
    assert not permission.has_permission(Request("POST", courier()), View("escalate"))
    assert permission.denial is not None
    assert permission.denial.rule is Rule.ACTION_KNOWN


def test_plain_apiview_maps_the_http_method() -> None:
    permission = ShipmentAccess()
    assert permission.has_permission(Request("GET", courier()), View())


def test_request_without_an_actor_is_anonymous() -> None:
    permission = ShipmentAccess()
    assert not permission.has_permission(Request(user=Principal()), View("list"))
    assert permission.denial is not None
    assert permission.denial.actor == "anonymous"
    assert permission.denial.rule is Rule.ACTOR_KNOWN


def test_stale_role_is_a_denial_not_an_error() -> None:
    permission = ShipmentAccess()
    request = Request(user=Principal(role="intern"))
    assert not permission.has_permission(request, View("list"))
    assert permission.denial is not None
    assert permission.denial.rule is Rule.ACTOR_KNOWN


def test_object_permission_follows_the_declared_slice() -> None:
    permission = ShipmentAccess()
    request = Request("POST", courier(7))
    assert permission.has_object_permission(request, View("deliver"), Shipment(7))


def test_row_outside_the_slice_carries_the_ownership_rule() -> None:
    permission = ShipmentAccess()
    request = Request("POST", courier(7))
    assert not permission.has_object_permission(request, View("deliver"), Shipment(9))
    assert permission.denial is not None
    assert permission.denial.rule is Rule.OBJECT_OWNED
    assert permission.message["reason"] == (
        "this shipment is outside shipment.own_assignment"
    )


def test_mixin_narrows_the_list_by_the_same_declaration() -> None:
    view = ShipmentView(Request(user=courier(7)), action="list")
    assert view.get_queryset().filters == {"courier_id": 7}


def test_mixin_leaves_an_unscoped_actor_alone() -> None:
    view = ShipmentView(Request(user=Principal(role="support")), action="list")
    assert view.get_queryset() is view.queryset


def test_mixin_empties_the_list_without_an_actor() -> None:
    view = ShipmentView(Request(user=Principal()), action="list")
    assert view.get_queryset().empty


def test_factory_rejects_declarations_the_matrix_does_not_know() -> None:
    with pytest.raises(ValueError):
        scoped_permission("shipment", {"deliver": "shipment.teleport"})
    with pytest.raises(ValueError):
        scoped_permission("warehouse")
