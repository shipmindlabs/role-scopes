# role-scopes

Multi-actor authorization for Django backends serving warehouse, courier, support
and back-office actors: declarative policies, queryset scoping and object
ownership checks.

## Status

Early: the permission matrix and explainable permission checks are in place;
queryset scoping and ownership checks are next.

## Installation

```bash
pip install role-scopes
```

## Usage

Permissions are declared as data in one place and read by every check:

```python
from role_scopes import Actor, Permission, check, require

check(Actor.SUPPORT, Permission.ORDER_CANCEL).allowed
# True
```

A denial names the actor, the action and the rule that refused, so the same
value can be logged and returned to the client:

```python
decision = check("courier", "order.refund")

str(decision.denial)
# 'courier may not order.refund: courier is not granted order.refund [permission.granted]'

decision.denial.as_dict()
# {'actor': 'courier', 'action': 'order.refund',
#  'rule': 'permission.granted', 'reason': 'courier is not granted order.refund'}
```

In a view, `require()` raises a `PermissionDenied` that Django already turns
into a 403 while carrying the structured denial for the error body:

```python
from role_scopes import PermissionDenied, require

try:
    require(request.user.role, Permission.INVENTORY_ADJUST)
except PermissionDenied as exc:
    return JsonResponse(exc.denial.as_dict(), status=403)
```

Unknown actors and unknown actions are denials too, tagged with the
`actor.known` and `action.known` rules instead of raising.

## License

MIT

---

Maintained by [Shipmind Labs](https://shipmindlabs.com).
