# role-scopes

Multi-actor authorization for Django backends serving warehouse, courier, support
and back-office actors: declarative policies, queryset scoping and object
ownership checks.

## Status

Early: the permission matrix, explainable permission checks, queryset scoping,
object ownership checks and the optional Django admin and REST Framework
adapters are in place.

## Installation

```bash
pip install role-scopes
pip install "role-scopes[rest]"  # with the Django REST Framework adapter
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

### Django REST Framework

The adapter in `role_scopes.contrib.rest_framework` turns the same declarations
into the objects a DRF view expects, so an endpoint stops hand-rolling the role
checks its neighbours already spell out:

```python
from rest_framework import viewsets
from role_scopes import Permission
from role_scopes.contrib.rest_framework import ScopedQuerysetMixin, scoped_permission

ShipmentAccess = scoped_permission(
    "shipment",
    {
        "deliver": Permission.SHIPMENT_DELIVER,
        "assign": Permission.SHIPMENT_ASSIGN,
    },
)


class ShipmentViewSet(ScopedQuerysetMixin, viewsets.ModelViewSet):
    queryset = Shipment.objects.all()
    serializer_class = ShipmentSerializer
    permission_classes = [ShipmentAccess]
```

Keys are viewset actions (`deliver`, `assign`) or HTTP methods (`POST`) for a
plain `APIView`. `list` and `retrieve` fall back to `shipment.view` and `create`
to `shipment.create`; `update`, `destroy` and every custom action must be
mapped, because the matrix names domain actions rather than CRUD and an
undeclared POST route would otherwise inherit `create`. An action with no
permission mapped is refused rather than allowed, and a permission the matrix
does not declare raises when the class is built, not on the first request that
reaches the route.

One class covers both questions DRF asks: `has_object_permission()` runs
`check_object()` on the detail routes, and `ScopedQuerysetMixin` narrows the
list with `scope_queryset()` from the same declaration, so a courier never sees
a row it may not open and never opens a row it may not see.

The denial is the 403 body:

```python
{'actor': 'courier', 'action': 'shipment.deliver', 'rule': 'object.owned',
 'reason': 'this shipment is outside shipment.own_assignment'}
```

DRF renders it from `permission.message`; a view or exception handler that wants
the structured value reads `permission.denial`. The actor is read from
`request.user.role` (`actor_attribute` renames it), and a request carrying no
actor is denied as `anonymous` with the `actor.known` rule.

### Django admin, separated by role

The checks above are declarations and functions. The adapter in
`role_scopes.contrib.admin` is the optional layer that speaks Django's own
vocabulary; nothing in the core imports it, and it belongs in an app's
`admin.py` or a migration rather than in settings.

Declared permissions get the names `auth` would give them, so a model can carry
the domain actions Django does not create by itself:

```python
from role_scopes.contrib.admin import codename_for, model_permissions

codename_for(Permission.ORDER_CANCEL)  # 'cancel_order'
codename_for(Permission.ORDER_CREATE)  # 'add_order' — create is Django's add

class Order(models.Model):
    class Meta:
        permissions = model_permissions("order")
        # [('approve_return', ...)] style entries, minus the four Django adds
```

One group per actor holds exactly what the matrix grants it. `sync_groups()`
replaces the group's permissions instead of adding to them, so it is safe to
re-run from a data migration and a capability dropped from the matrix leaves
the group with it:

```python
from role_scopes.contrib.admin import sync_groups

APPS = {"order": "orders", "shipment": "orders", "inventory": "warehouse"}

sync_groups(APPS)
# {'role_scopes:courier': 4, 'role_scopes:warehouse': 6, ...}
```

Resources absent from the mapping are skipped, so a project may model only part
of the matrix.

A scoped admin narrows the changelist and refuses the rows outside the slice,
which is what lets support and warehouse staff share one admin site:

```python
from role_scopes.contrib.admin import ScopedModelAdmin

@admin.register(Shipment)
class ShipmentAdmin(ScopedModelAdmin):
    resource = "shipment"
    change_permission = Permission.SHIPMENT_DELIVER
```

The actor is read from `request.user.role` (`actor_attribute` renames it), and a
superuser without one is treated as back-office unless `superuser_actor` is set
to `None`. View and add fall back to `<resource>.view` and `<resource>.create`;
change and delete have no fallback, because the matrix names domain actions
rather than CRUD, and an admin action with no permission mapped is refused.

## License

MIT

---

Maintained by [Shipmind Labs](https://shipmindlabs.com).
