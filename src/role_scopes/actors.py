"""Actors of an operations backend and the permissions they hold.

This module is the single place where the permission matrix is declared as
data: policies, queryset scoping and ownership checks read from it instead of
restating rules of their own.
"""

from __future__ import annotations

from enum import Enum
from types import MappingProxyType
from typing import Mapping

__all__ = [
    "ACTOR_PERMISSIONS",
    "Actor",
    "Permission",
    "actors_with",
    "has_permission",
    "permissions_for",
]


class Actor(str, Enum):
    """Party acting on the system."""

    CUSTOMER = "customer"
    COURIER = "courier"
    WAREHOUSE = "warehouse"
    RECEIVING = "receiving"
    SUPPORT = "support"
    BACK_OFFICE = "back_office"


class Permission(str, Enum):
    """Atomic capability, named ``<resource>.<action>``."""

    ORDER_VIEW = "order.view"
    ORDER_CREATE = "order.create"
    ORDER_CANCEL = "order.cancel"
    ORDER_REFUND = "order.refund"

    SHIPMENT_VIEW = "shipment.view"
    SHIPMENT_ASSIGN = "shipment.assign"
    SHIPMENT_PICKUP = "shipment.pickup"
    SHIPMENT_DELIVER = "shipment.deliver"
    SHIPMENT_REROUTE = "shipment.reroute"

    INVENTORY_VIEW = "inventory.view"
    INVENTORY_COUNT = "inventory.count"
    INVENTORY_ADJUST = "inventory.adjust"

    RECEIVING_VIEW = "receiving.view"
    RECEIVING_ACCEPT = "receiving.accept"
    RECEIVING_REJECT = "receiving.reject"

    RETURN_VIEW = "return.view"
    RETURN_CREATE = "return.create"
    RETURN_INSPECT = "return.inspect"
    RETURN_APPROVE = "return.approve"

    TICKET_VIEW = "ticket.view"
    TICKET_CREATE = "ticket.create"
    TICKET_COMMENT = "ticket.comment"
    TICKET_CLOSE = "ticket.close"

    REPORT_VIEW = "report.view"
    USER_VIEW = "user.view"
    USER_MANAGE = "user.manage"


ACTOR_PERMISSIONS: Mapping[Actor, frozenset[Permission]] = MappingProxyType(
    {
        Actor.CUSTOMER: frozenset(
            {
                Permission.ORDER_VIEW,
                Permission.ORDER_CREATE,
                Permission.ORDER_CANCEL,
                Permission.SHIPMENT_VIEW,
                Permission.RETURN_VIEW,
                Permission.RETURN_CREATE,
                Permission.TICKET_VIEW,
                Permission.TICKET_CREATE,
                Permission.TICKET_COMMENT,
            }
        ),
        Actor.COURIER: frozenset(
            {
                Permission.ORDER_VIEW,
                Permission.SHIPMENT_VIEW,
                Permission.SHIPMENT_PICKUP,
                Permission.SHIPMENT_DELIVER,
            }
        ),
        Actor.WAREHOUSE: frozenset(
            {
                Permission.ORDER_VIEW,
                Permission.SHIPMENT_VIEW,
                Permission.SHIPMENT_ASSIGN,
                Permission.INVENTORY_VIEW,
                Permission.INVENTORY_COUNT,
                Permission.INVENTORY_ADJUST,
                Permission.RETURN_VIEW,
                Permission.RETURN_INSPECT,
            }
        ),
        Actor.RECEIVING: frozenset(
            {
                Permission.RECEIVING_VIEW,
                Permission.RECEIVING_ACCEPT,
                Permission.RECEIVING_REJECT,
                Permission.INVENTORY_VIEW,
                Permission.INVENTORY_COUNT,
            }
        ),
        Actor.SUPPORT: frozenset(
            {
                Permission.ORDER_VIEW,
                Permission.ORDER_CANCEL,
                Permission.SHIPMENT_VIEW,
                Permission.SHIPMENT_REROUTE,
                Permission.RETURN_VIEW,
                Permission.RETURN_CREATE,
                Permission.RETURN_APPROVE,
                Permission.TICKET_VIEW,
                Permission.TICKET_CREATE,
                Permission.TICKET_COMMENT,
                Permission.TICKET_CLOSE,
                Permission.USER_VIEW,
            }
        ),
        # Back-office runs the business and holds every capability.
        Actor.BACK_OFFICE: frozenset(Permission),
    }
)


def permissions_for(actor: Actor | str) -> frozenset[Permission]:
    """Return the permissions granted to ``actor``."""
    return ACTOR_PERMISSIONS[Actor(actor)]


def has_permission(actor: Actor | str, permission: Permission | str) -> bool:
    """Tell whether ``actor`` holds ``permission``."""
    return Permission(permission) in permissions_for(actor)


def actors_with(permission: Permission | str) -> frozenset[Actor]:
    """Return every actor holding ``permission``."""
    wanted = Permission(permission)
    return frozenset(
        actor for actor, granted in ACTOR_PERMISSIONS.items() if wanted in granted
    )
