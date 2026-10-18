"""Declaration lint: the capability table read against the slice table.

Capabilities live in one table and slices in another, and the pair only means
what it looks like when the two agree. A grant whose resource has no slice
reads as a capability and denies every row. A slice no grant reaches narrows a
queryset nobody asks for. A slice keyed by a resource no permission names is a
typo that quietly reads as ``Scope.NOTHING``. None of the three raises at
import time, so they are reported here as findings a test or a deploy step can
fail on.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from role_scopes.actors import ACTOR_PERMISSIONS, Actor, Permission
from role_scopes.scopes import ACTOR_SCOPES, RESOURCES, Scope, resource_of

__all__ = [
    "Finding",
    "FindingKind",
    "verify_declarations",
]


class FindingKind(str, Enum):
    """What the lint found, named after the half of the pair at fault."""

    GRANT_WITHOUT_SLICE = "grant.without_slice"
    SLICE_WITHOUT_GRANT = "slice.without_grant"
    SLICE_UNKNOWN_RESOURCE = "slice.unknown_resource"


@dataclass(frozen=True, slots=True)
class Finding:
    """One disagreement between the capability table and the slice table."""

    kind: FindingKind
    actor: str
    resource: str
    reason: str
    actions: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-ready mapping for a report or a failing assertion."""
        return {
            "kind": self.kind.value,
            "actor": self.actor,
            "resource": self.resource,
            "reason": self.reason,
            "actions": list(self.actions),
        }

    def __str__(self) -> str:
        return f"{self.reason} [{self.kind.value}]"


def _granted_resources(
    permissions: Iterable[Permission | str],
) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = {}
    for permission in permissions:
        resolved = Permission(permission)
        grouped.setdefault(resource_of(resolved), []).append(resolved.value)
    return {resource: tuple(sorted(actions)) for resource, actions in grouped.items()}


def verify_declarations(
    permissions: Mapping[Actor | str, Iterable[Permission | str]] = ACTOR_PERMISSIONS,
    scopes: Mapping[Actor | str, Mapping[str, Scope]] = ACTOR_SCOPES,
) -> tuple[Finding, ...]:
    """Read the capability table and the slice table against each other.

    Defaults to the shipped tables, so a project that keeps them asserts the
    pair agrees in one line and a project that declares its own gets the same
    reading. An actor present in one table and absent from the other is read as
    an empty row rather than an error, and an explicitly declared
    ``Scope.NOTHING`` is a decision somebody wrote down rather than a finding.
    """
    granted = {
        Actor(actor): _granted_resources(held) for actor, held in permissions.items()
    }
    declared = {Actor(actor): dict(slices) for actor, slices in scopes.items()}

    findings: list[Finding] = []
    for actor in sorted(set(granted) | set(declared), key=lambda member: member.value):
        label = actor.value
        resources = granted.get(actor, {})
        slices = declared.get(actor, {})

        for resource, actions in sorted(resources.items()):
            if resource in slices:
                continue
            findings.append(
                Finding(
                    FindingKind.GRANT_WITHOUT_SLICE,
                    label,
                    resource,
                    f"{label} is granted {', '.join(actions)} but declares no "
                    f"{resource} slice, so every row is denied",
                    actions,
                )
            )

        for resource, scope in sorted(slices.items()):
            if resource not in RESOURCES:
                findings.append(
                    Finding(
                        FindingKind.SLICE_UNKNOWN_RESOURCE,
                        label,
                        resource,
                        f"{label} declares a slice keyed {resource!r}, which no "
                        f"permission names, so the resource it was meant for "
                        f"reads as Scope.NOTHING",
                    )
                )
                continue
            if resource in resources:
                continue
            findings.append(
                Finding(
                    FindingKind.SLICE_WITHOUT_GRANT,
                    label,
                    resource,
                    f"{label} declares the {scope.label} slice but is granted no "
                    f"{resource} action, so nothing reads it",
                )
            )

    return tuple(findings)
