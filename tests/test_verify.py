"""The lint reads the two tables against each other.

The shipped tables are expected to be silent; the findings are provoked with
hand-written tables, so the expectations do not come from the declaration under
test.
"""

from __future__ import annotations

import pytest

from role_scopes import (
    ACTOR_PERMISSIONS,
    ACTOR_SCOPES,
    Actor,
    Finding,
    FindingKind,
    Permission,
    Scope,
    verify_declarations,
)


def test_the_shipped_tables_agree() -> None:
    assert verify_declarations() == ()
    assert verify_declarations(ACTOR_PERMISSIONS, ACTOR_SCOPES) == ()


def test_a_grant_without_a_slice_denies_every_row() -> None:
    findings = verify_declarations(
        {Actor.COURIER: {Permission.SHIPMENT_VIEW, Permission.SHIPMENT_DELIVER}},
        {Actor.COURIER: {}},
    )
    assert len(findings) == 1
    finding = findings[0]
    assert finding.kind is FindingKind.GRANT_WITHOUT_SLICE
    assert finding.actor == "courier"
    assert finding.resource == "shipment"
    assert finding.actions == ("shipment.deliver", "shipment.view")
    assert finding.reason == (
        "courier is granted shipment.deliver, shipment.view but declares no "
        "shipment slice, so every row is denied"
    )
    assert str(finding) == f"{finding.reason} [grant.without_slice]"


def test_a_slice_with_no_grant_is_read_by_nobody() -> None:
    findings = verify_declarations(
        {Actor.COURIER: {Permission.SHIPMENT_VIEW}},
        {
            Actor.COURIER: {
                "shipment": Scope.owned("shipment.own", courier_id="courier_id"),
                "inventory": Scope.owned("inventory.own_store", store_id="store_id"),
            }
        },
    )
    assert len(findings) == 1
    finding = findings[0]
    assert finding.kind is FindingKind.SLICE_WITHOUT_GRANT
    assert finding.resource == "inventory"
    assert finding.actions == ()
    assert finding.reason == (
        "courier declares the inventory.own_store slice but is granted no "
        "inventory action, so nothing reads it"
    )


def test_a_misspelled_slice_key_is_named_as_the_typo_it_is() -> None:
    findings = verify_declarations(
        {Actor.COURIER: {Permission.SHIPMENT_VIEW}},
        {
            Actor.COURIER: {
                "shipmnet": Scope.owned("shipment.own", courier_id="courier_id")
            }
        },
    )
    kinds = [finding.kind for finding in findings]
    assert kinds == [
        FindingKind.GRANT_WITHOUT_SLICE,
        FindingKind.SLICE_UNKNOWN_RESOURCE,
    ]
    unknown = findings[1]
    assert unknown.resource == "shipmnet"
    assert "Scope.NOTHING" in unknown.reason


def test_an_unknown_key_is_not_also_reported_as_a_slice_without_a_grant() -> None:
    findings = verify_declarations(
        {Actor.SUPPORT: {Permission.TICKET_VIEW}},
        {
            Actor.SUPPORT: {
                "ticket": Scope.EVERYTHING,
                "tickets": Scope.EVERYTHING,
            }
        },
    )
    assert len(findings) == 1
    assert findings[0].kind is FindingKind.SLICE_UNKNOWN_RESOURCE


def test_an_explicit_nothing_is_a_decision_not_a_finding() -> None:
    findings = verify_declarations(
        {Actor.COURIER: {Permission.SHIPMENT_VIEW}},
        {Actor.COURIER: {"shipment": Scope.NOTHING}},
    )
    assert findings == ()


def test_an_actor_absent_from_the_slice_table_loses_every_resource() -> None:
    findings = verify_declarations(
        {Actor.RECEIVING: {Permission.RECEIVING_VIEW, Permission.INVENTORY_VIEW}},
        {},
    )
    assert {finding.resource for finding in findings} == {"inventory", "receiving"}
    assert {finding.kind for finding in findings} == {
        FindingKind.GRANT_WITHOUT_SLICE
    }


def test_an_actor_absent_from_the_capability_table_reaches_nothing() -> None:
    findings = verify_declarations(
        {},
        {Actor.RECEIVING: {"receiving": Scope.owned("receiving.own", a="a")}},
    )
    assert len(findings) == 1
    assert findings[0].kind is FindingKind.SLICE_WITHOUT_GRANT
    assert findings[0].actor == "receiving"


def test_both_halves_of_a_mismatch_are_reported_per_actor() -> None:
    findings = verify_declarations(
        {
            Actor.COURIER: {Permission.SHIPMENT_VIEW},
            Actor.WAREHOUSE: {Permission.INVENTORY_VIEW},
        },
        {
            Actor.COURIER: {"order": Scope.owned("order.own", a="a")},
            Actor.WAREHOUSE: {
                "inventory": Scope.owned("inventory.own_store", store_id="store_id")
            },
        },
    )
    assert [(finding.actor, finding.resource, finding.kind) for finding in findings] == [
        ("courier", "shipment", FindingKind.GRANT_WITHOUT_SLICE),
        ("courier", "order", FindingKind.SLICE_WITHOUT_GRANT),
    ]


def test_tables_keyed_by_plain_strings_are_read_the_same() -> None:
    findings = verify_declarations({"courier": {"shipment.view"}}, {"courier": {}})
    assert len(findings) == 1
    assert findings[0].actor == "courier"
    assert findings[0].actions == ("shipment.view",)


def test_a_finding_is_json_ready() -> None:
    findings = verify_declarations(
        {Actor.COURIER: {Permission.SHIPMENT_VIEW}}, {Actor.COURIER: {}}
    )
    assert findings[0].as_dict() == {
        "kind": "grant.without_slice",
        "actor": "courier",
        "resource": "shipment",
        "reason": findings[0].reason,
        "actions": ["shipment.view"],
    }


def test_an_actor_the_tables_do_not_know_is_an_error() -> None:
    with pytest.raises(ValueError):
        verify_declarations({"intern": {"order.view"}}, {})


def test_a_finding_cannot_be_edited_after_the_fact() -> None:
    finding = Finding(FindingKind.SLICE_WITHOUT_GRANT, "courier", "order", "because")
    with pytest.raises(AttributeError):
        finding.resource = "shipment"  # type: ignore[misc]
