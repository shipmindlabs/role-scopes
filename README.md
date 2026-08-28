# role-scopes

Multi-actor authorization for Django backends serving warehouse, courier, support
and back-office actors: declarative policies, queryset scoping and object
ownership checks.

## Status

Early: the permission matrix, explainable permission checks, queryset scoping
and object ownership checks are in place.

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

### Object ownership

A permission says what an actor may do; it never says which objects are theirs.
The worth naming mistake this closes: detail and action endpoints checked the
role and stopped there — a courier may deliver shipments — without asking
whether *this* shipment was assigned to *that* courier, so any courier could
act on any order that reached its URL.

`check_object()` asks both questions against the slice already declared for
queryset scoping, so the row a list view hides is the row a detail view
refuses:

```python
from role_scopes import Permission, check_object, owns, require_object

owns("courier", Permission.SHIPMENT_DELIVER, shipment, request.user)
# True only when shipment.courier_id == request.user.courier_id

decision = check_object("courier", "order.view", someone_elses_order, request.user)
str(decision.denial)
# 'courier may not order.view: this order is outside order.own_assignment [object.owned]'
```

`require_object()` raises the same `PermissionDenied` as `require()`, so a view
renders one error body for both failures:

```python
require_object(request.user.role, Permission.SHIPMENT_DELIVER, shipment, request.user)
```

Ownership failures carry the `object.owned` rule, which separates "you may not
do this at all" from "not on this row" in logs. Lookups spanning relations are
followed on the object the way the queryset would join them, so a courier's
reach over an order is decided by `order.shipment.courier_id`. An actor whose
slice is `everything` reaches every row, a resource with no declared slice
reaches none, and an object missing the field the slice narrows on raises
`MissingObjectKey` rather than passing quietly.

## License

MIT

---

Maintained by [Shipmind Labs](https://shipmindlabs.com).
