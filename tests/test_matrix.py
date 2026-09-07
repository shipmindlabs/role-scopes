"""The permission matrix, cell by cell: every actor against every action.

The grants are restated here by hand instead of being read back from
``ACTOR_PERMISSIONS``: expectations derived from the table under test would
agree with whatever that table happened to say, including a capability nobody
meant to hand out.
"""

from __future__ import annotations

import pytest

from role_scopes import (
    ACTOR_PERMISSIONS,
    Actor,
    Permission,
    PermissionDenied,
    Rule,
    actors_with,
    check,
    has_permission,
    permissions_for,
    require,
)

ACTIONS: tuple[str, ...] = (
    "order.view",
    "order.create",
    "order.cancel",
    "order.refund",
    "shipment.view",
    "shipment.assign",
    "shipment.pickup",
    "shipment.deliver",
    "shipment.reroute",
    "inventory.view",
    "inventory.count",
    "inventory.adjust",
    "receiving.view",
    "receiving.accept",
    "receiving.reject",
    "return.view",
    "return.create",
    "return.inspect",
    "return.approve",
    "ticket.view",
    "ticket.create",
    "ticket.comment",
    "ticket.close",
    "report.view",
    "user.view",
    "user.manage",
)

GRANTED: dict[str, frozenset[str]] = {
    "customer": frozenset(
        {
            "order.view",
            "order.create",
            "order.cancel",
            "shipment.view",
            "return.view",
            "return.create",
            "ticket.view",
            "ticket.create",
            "ticket.comment",
        }
    ),
    "courier": frozenset(
        {
            "order.view",
            "shipment.view",
            "shipment.pickup",
            "shipment.deliver",
        }
    ),
    "warehouse": frozenset(
        {
            "order.view",
            "shipment.view",
            "shipment.assign",
            "inventory.view",
            "inventory.count",
            "inventory.adjust",
            "return.view",
            "return.inspect",
        }
    ),
    "receiving": frozenset(
        {
            "receiving.view",
            "receiving.accept",
            "receiving.reject",
            "inventory.view",
            "inventory.count",
        }
    ),
    "support": frozenset(
        {
            "order.view",
            "order.cancel",
            "shipment.view",
            "shipment.reroute",
            "return.view",
            "return.create",
            "return.approve",
            "ticket.view",
            "ticket.create",
            "ticket.comment",
            "ticket.close",
            "user.view",
        }
    ),
    "back_office": frozenset(ACTIONS),
}

# Actions no operational actor may reach: money leaves the company, the
# business is measured, and accounts are handed out.
PRIVILEGED: tuple[str, ...] = ("order.refund", "report.view", "user.manage")

CELLS: tuple[tuple[str, str, bool], ...] = tuple(
    (actor, action, action in GRANTED[actor])
    for actor in GRANTED
    for action in ACTIONS
)
CELL_IDS = [f"{actor}-{action}" for actor, action, _ in CELLS]

ALLOWED: tuple[tuple[str, str], ...] = tuple(
    (actor, action) for actor, action, allowed in CELLS if allowed
)
ALLOWED_IDS = [f"{actor}-{action}" for actor, action in ALLOWED]

DENIED: tuple[tuple[str, str], ...] = tuple(
    (actor, action) for actor, action, allowed in CELLS if not allowed
)
DENIED_IDS = [f"{actor}-{action}" for actor, action in DENIED]


def test_the_table_covers_every_declared_action() -> None:
    assert set(ACTIONS) == {permission.value for permission in Permission}
    assert len(ACTIONS) == len(set(ACTIONS))


def test_the_table_covers_every_declared_actor() -> None:
    assert set(GRANTED) == {actor.value for actor in Actor}


@pytest.mark.parametrize("actor", sorted(GRANTED))
def test_the_row_of_an_actor_matches_the_declaration(actor: str) -> None:
    granted = {permission.value for permission in permissions_for(actor)}
    assert granted == GRANTED[actor]


@pytest.mark.parametrize(("actor", "action", "allowed"), CELLS, ids=CELL_IDS)
def test_every_cell_of_the_matrix(actor: str, action: str, allowed: bool) -> None:
    decision = check(actor, action)
    assert decision.allowed is allowed
    assert bool(decision) is allowed
    assert has_permission(actor, action) is allowed
    assert decision.actor == actor
    assert decision.action == action


@pytest.mark.parametrize(("actor", "action"), ALLOWED, ids=ALLOWED_IDS)
def test_a_granted_cell_carries_no_denial(actor: str, action: str) -> None:
    assert check(actor, action).denial is None
    require(actor, action)


@pytest.mark.parametrize(("actor", "action"), DENIED, ids=DENIED_IDS)
def test_a_denied_cell_names_the_actor_the_action_and_the_rule(
    actor: str, action: str
) -> None:
    denial = check(actor, action).denial
    assert denial is not None
    reason = f"{actor} is not granted {action}"
    assert denial.rule is Rule.PERMISSION_GRANTED
    assert denial.as_dict() == {
        "actor": actor,
        "action": action,
        "rule": "permission.granted",
        "reason": reason,
    }
    assert str(denial) == f"{actor} may not {action}: {reason} [permission.granted]"


@pytest.mark.parametrize(("actor", "action"), DENIED, ids=DENIED_IDS)
def test_a_denied_cell_raises_the_same_denial_from_require(
    actor: str, action: str
) -> None:
    with pytest.raises(PermissionDenied) as raised:
        require(actor, action)
    assert raised.value.denial == check(actor, action).denial


@pytest.mark.parametrize("action", ACTIONS)
def test_actors_with_reads_the_column(action: str) -> None:
    assert actors_with(action) == frozenset(
        Actor(actor) for actor, granted in GRANTED.items() if action in granted
    )


@pytest.mark.parametrize("action", ACTIONS)
def test_every_action_is_held_by_someone(action: str) -> None:
    assert actors_with(action)


@pytest.mark.parametrize("action", PRIVILEGED)
def test_the_privileged_actions_stay_with_back_office(action: str) -> None:
    assert actors_with(action) == frozenset({Actor.BACK_OFFICE})


def test_back_office_holds_every_action() -> None:
    assert permissions_for(Actor.BACK_OFFICE) == frozenset(Permission)


def test_an_enum_member_and_its_value_are_the_same_cell() -> None:
    assert check(Actor.COURIER, Permission.SHIPMENT_DELIVER).allowed
    assert check("courier", "shipment.deliver").allowed
    assert has_permission(Actor.COURIER, "shipment.deliver")


def test_an_unknown_actor_is_a_denial_not_an_error() -> None:
    denial = check("intern", Permission.ORDER_VIEW).denial
    assert denial is not None
    assert denial.rule is Rule.ACTOR_KNOWN
    assert denial.reason == "'intern' is not a known actor"


def test_an_unknown_action_is_a_denial_not_an_error() -> None:
    denial = check(Actor.SUPPORT, "order.teleport").denial
    assert denial is not None
    assert denial.rule is Rule.ACTION_KNOWN
    assert denial.reason == "'order.teleport' is not a known permission"


def test_the_actor_is_answered_before_the_action() -> None:
    denial = check("intern", "order.teleport").denial
    assert denial is not None
    assert denial.rule is Rule.ACTOR_KNOWN


def test_permissions_for_rejects_an_actor_the_matrix_does_not_know() -> None:
    with pytest.raises(ValueError):
        permissions_for("intern")


def test_the_matrix_cannot_be_edited_at_runtime() -> None:
    with pytest.raises(TypeError):
        ACTOR_PERMISSIONS[Actor.COURIER] = frozenset()  # type: ignore[index]
