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

## Multi-actor backends, done once

A delivery backend looks like one product and answers to six audiences. The
customer places an order and watches it move. The courier carries it. The
warehouse picks it, assigns it and counts what is left on the shelf. Receiving
takes pallets in from suppliers and never touches a customer order. Support
answers for all of the above and has to see across every store and every route
to do it. Back-office runs the business: refunds, reports, accounts.

Five of them read the `order` table and no two of them read the same rows. That
is the shape of the problem: *what may this actor do* and *which rows are
theirs* are two different questions, and a backend that answers only the first
one hands every courier the whole fleet.

### Declaring the audiences

Capabilities are one table, in `role_scopes.actors`. Permissions are named
`<resource>.<action>` after the domain rather than after CRUD, because
`shipment.reroute` is a thing support does and `PATCH` is not:

```python
class Actor(str, Enum):
    CUSTOMER = "customer"
    COURIER = "courier"
    WAREHOUSE = "warehouse"
    RECEIVING = "receiving"
    SUPPORT = "support"
    BACK_OFFICE = "back_office"


ACTOR_PERMISSIONS = {
    Actor.COURIER: frozenset(
        {
            Permission.ORDER_VIEW,
            Permission.SHIPMENT_VIEW,
            Permission.SHIPMENT_PICKUP,
            Permission.SHIPMENT_DELIVER,
        }
    ),
    # ...one row per actor; back-office holds frozenset(Permission)
}
```

Reach is the second table, in `role_scopes.scopes`, keyed by actor and by the
resource half of a permission. A slice is declared once and every
`shipment.*` permission narrows through it:

```python
ACTOR_SCOPES = {
    Actor.COURIER: {
        "order": Scope.owned("order.own_assignment", shipment__courier_id="courier_id"),
        "shipment": Scope.owned("shipment.own_assignment", courier_id="courier_id"),
    },
    Actor.WAREHOUSE: {
        "order": Scope.owned("order.own_store", store_id="store_id"),
        "inventory": Scope.owned("inventory.own_store", store_id="store_id"),
    },
    Actor.SUPPORT: {
        "order": Scope.EVERYTHING,
        "shipment": Scope.EVERYTHING,
    },
}
```

A slice has three shapes: `Scope.EVERYTHING` for the actors that answer for the
whole business, `Scope.owned()` for a filter resolved from the acting principal,
and nothing at all — an undeclared resource is `Scope.NOTHING`, so receiving
reaches no orders because nobody wrote down that it should. Visibility is
granted, never inherited.

Adding the seventh audience is a row in each table. No view changes, because no
view spells a rule out for itself.

### The ownership trap

Here is the endpoint that ships in most multi-actor backends on the first pass:

```python
@api_view(["POST"])
def deliver(request, shipment_id):
    require(request.user.role, Permission.SHIPMENT_DELIVER)
    shipment = get_object_or_404(Shipment, pk=shipment_id)
    shipment.mark_delivered()
```

The check is real and it passes for the wrong person. Every courier holds
`shipment.deliver` — that is what makes them a courier — so courier 7 posting to
shipment 8821, assigned to courier 12, marks somebody else's parcel delivered.
The list endpoint was scoped correctly and never showed 8821 to courier 7, which
is exactly what makes the bug survive review: hidden is not denied, and an id is
an integer.

The fix is to ask the second question against the same declaration the list used:

```python
@api_view(["POST"])
def deliver(request, shipment_id):
    shipment = get_object_or_404(Shipment, pk=shipment_id)
    require_object(request.user.role, Permission.SHIPMENT_DELIVER, shipment, request.user)
    shipment.mark_delivered()
```

The tempting shortcut — `if shipment.courier_id != request.user.courier_id:` in
the view — is right for couriers and wrong for the other five audiences. Support
reaches every shipment and would be locked out, warehouse owns by `store_id`,
and the courier's reach over an *order* is not a column at all but
`order.shipment.courier_id`. Written by hand it is six branches per endpoint,
drifting apart one endpoint at a time; read from `ACTOR_SCOPES` it is one line
that already agrees with the queryset.

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

`check_object()` asks the ownership question against the slice already declared
for queryset scoping, so the row a list view hides is the row a detail view
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
