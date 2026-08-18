"""Permission checks that explain their denials.

A denial names the actor, the action and the rule that refused. The same
structure serves a log line and the body of a 403 response, so a support
engineer reading logs and a client reading JSON see the same answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied

from role_scopes.actors import Actor, Permission, permissions_for

__all__ = [
    "Decision",
    "Denial",
    "PermissionDenied",
    "Rule",
    "check",
    "require",
]


class Rule(str, Enum):
    """Rule consulted by :func:`check`, listed in the order it is applied."""

    ACTOR_KNOWN = "actor.known"
    ACTION_KNOWN = "action.known"
    PERMISSION_GRANTED = "permission.granted"


@dataclass(frozen=True, slots=True)
class Denial:
    """Why a check refused: the actor, the action and the rule that said no."""

    actor: str
    action: str
    rule: Rule
    reason: str

    def as_dict(self) -> dict[str, str]:
        """Return a JSON-ready mapping for API error bodies."""
        return {
            "actor": self.actor,
            "action": self.action,
            "rule": self.rule.value,
            "reason": self.reason,
        }

    def __str__(self) -> str:
        return f"{self.actor} may not {self.action}: {self.reason} [{self.rule.value}]"


@dataclass(frozen=True, slots=True)
class Decision:
    """Outcome of a check; falsy when denied, with the denial attached."""

    actor: str
    action: str
    denial: Denial | None = None

    @property
    def allowed(self) -> bool:
        """Tell whether the action was permitted."""
        return self.denial is None

    def __bool__(self) -> bool:
        return self.denial is None


class PermissionDenied(DjangoPermissionDenied):
    """Denial raised as an exception, carrying the structured reason.

    Subclasses the Django exception so existing handlers keep returning 403
    while views that know about role-scopes can render ``exc.denial``.
    """

    def __init__(self, denial: Denial) -> None:
        super().__init__(str(denial))
        self.denial = denial


def _label(value: object) -> str:
    return value.value if isinstance(value, Enum) else str(value)


def check(actor: Actor | str, action: Permission | str) -> Decision:
    """Decide whether ``actor`` may perform ``action``.

    Unknown actors and unknown actions are denials rather than errors: a
    caller passing a stale role name gets an answer it can log and return.
    """
    actor_label = _label(actor)
    action_label = _label(action)

    def denied(rule: Rule, reason: str) -> Decision:
        return Decision(
            actor_label,
            action_label,
            Denial(actor_label, action_label, rule, reason),
        )

    try:
        resolved_actor = Actor(actor)
    except ValueError:
        return denied(Rule.ACTOR_KNOWN, f"{actor_label!r} is not a known actor")

    try:
        resolved_action = Permission(action)
    except ValueError:
        return denied(Rule.ACTION_KNOWN, f"{action_label!r} is not a known permission")

    if resolved_action not in permissions_for(resolved_actor):
        return denied(
            Rule.PERMISSION_GRANTED,
            f"{actor_label} is not granted {action_label}",
        )

    return Decision(actor_label, action_label)


def require(actor: Actor | str, action: Permission | str) -> None:
    """Raise :class:`PermissionDenied` unless ``actor`` may perform ``action``."""
    decision = check(actor, action)
    if decision.denial is not None:
        raise PermissionDenied(decision.denial)
