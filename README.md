# role-scopes

Multi-actor authorization for Django backends serving warehouse, courier, support
and back-office actors: declarative policies, queryset scoping and object
ownership checks.

## Status

Early: the permission matrix, explainable permission checks and queryset
scoping are in place; object ownership checks are next.

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

### Queryset scoping

Each actor sees only its own slice of a resource. The slice is declared next to
the permission, so a view narrows a queryset without restating the filter:

```python
from role_scopes import Permission, scope_queryset

# request.user carries `courier_id`
scope_queryset(Shipment.objects.all(), "courier", Permission.SHIPMENT_VIEW, request.user)
# Shipment.objects.filter(courier_id=request.user.courier_id)

scope_queryset(Order.objects.all(), "warehouse", Permission.ORDER_VIEW, request.user)
# Order.objects.filter(store_id=request.user.store_id)
```

Scoping is keyed by the resource half of a permission, so `shipment.view` and
`shipment.deliver` narrow the same way. The declaration is inspectable:

```python
from role_scopes import Actor, scope_for

scope_for(Actor.WAREHOUSE, Permission.INVENTORY_ADJUST).label
# 'inventory.own_store'
scope_for(Actor.SUPPORT, Permission.ORDER_VIEW).kind
# <ScopeKind.EVERYTHING: 'everything'>
```

The permission is checked before the slice is applied: an actor without the
capability, or a resource with no slice declared for that actor, gets an empty
queryset. A principal missing an attribute the slice filters on raises
`MissingScopeKey` rather than silently widening or emptying the result.

## License

MIT

---

Maintained by [Shipmind Labs](https://shipmindlabs.com).
