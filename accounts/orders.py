"""Order operations. Every change goes through here so it is always written to the OrderEvent audit log."""
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .menu import DELIVERY_FEE, FREE_DELIVERY_MINIMUM, MENU
from .models import Order, OrderEvent, OrderItem

DELIVERY_FIELDS = [
    "first_name",
    "last_name",
    "email",
    "phone",
    "address",
    "apartment",
    "city",
    "state",
    "zip_code",
    "delivery_instructions",
]


class OrderError(Exception):
    pass


def client_ip(request):
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    return forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")


def _record(order, event_type, actor=None, request=None, from_status="", to_status="", changes=None, note=""):
    return OrderEvent.objects.create(
        order=order,
        event_type=event_type,
        actor=actor,
        from_status=from_status,
        to_status=to_status,
        changes=changes or {},
        note=note,
        ip_address=client_ip(request),
    )


@transaction.atomic
def place_order(user, items, delivery, request=None):
    """Create an order with server-side prices. `items` is [{"meal_id", "quantity"}]."""
    # Merge duplicate lines and validate against the menu.
    quantities = {}
    for item in items:
        meal_id = item["meal_id"]
        if meal_id not in MENU:
            raise OrderError(f"Meal {meal_id} is not on the menu.")
        quantities[meal_id] = quantities.get(meal_id, 0) + item["quantity"]

    if not quantities:
        raise OrderError("An order needs at least one item.")

    subtotal = sum((MENU[m]["price"] * q for m, q in quantities.items()), Decimal("0"))
    delivery_fee = Decimal("0.00") if subtotal >= FREE_DELIVERY_MINIMUM else DELIVERY_FEE

    order = Order.objects.create(
        user=user,
        subtotal=subtotal,
        delivery_fee=delivery_fee,
        total=subtotal + delivery_fee,
        **{field: delivery.get(field, "") for field in DELIVERY_FIELDS},
    )
    OrderItem.objects.bulk_create(
        OrderItem(
            order=order,
            meal_id=meal_id,
            name=MENU[meal_id]["name"],
            unit_price=MENU[meal_id]["price"],
            quantity=quantity,
        )
        for meal_id, quantity in quantities.items()
    )

    _record(
        order,
        OrderEvent.EventType.CREATED,
        actor=user,
        request=request,
        to_status=order.status,
        changes={
            "items": [
                {"meal_id": m, "name": MENU[m]["name"], "unit_price": str(MENU[m]["price"]), "quantity": q}
                for m, q in quantities.items()
            ],
            "subtotal": str(subtotal),
            "delivery_fee": str(delivery_fee),
            "total": str(order.total),
        },
    )
    return order


@transaction.atomic
def change_status(order, new_status, actor=None, request=None, note=""):
    """Move an order to a new status if the transition is allowed, and audit it."""
    order = Order.objects.select_for_update().get(pk=order.pk)
    old_status = order.status

    if new_status == old_status:
        return order
    if not order.can_transition_to(new_status):
        raise OrderError(f"Can't change an order from {old_status} to {new_status}.")

    order.status = new_status
    order.save(update_fields=["status", "updated_at"])

    event_type = (
        OrderEvent.EventType.CANCELLED
        if new_status == Order.Status.CANCELLED
        else OrderEvent.EventType.STATUS_CHANGED
    )
    _record(
        order,
        event_type,
        actor=actor,
        request=request,
        from_status=old_status,
        to_status=new_status,
        changes={"status": [old_status, new_status]},
        note=note,
    )
    return order


def record_field_changes(order, before, actor=None, request=None, note=""):
    """Audit edits to non-status fields (e.g. staff fixing an address in the admin)."""
    changes = {
        field: [str(before[field]), str(getattr(order, field))]
        for field in before
        if before[field] != getattr(order, field)
    }
    if changes:
        _record(order, OrderEvent.EventType.UPDATED, actor=actor, request=request, changes=changes, note=note)


@transaction.atomic
def mark_paid(order, actor=None, request=None, note=""):
    """Record that an order has been paid, and audit it."""
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.payment_status == Order.PaymentStatus.PAID:
        return order
    if order.status == Order.Status.CANCELLED:
        raise OrderError("A cancelled order can't be marked as paid.")

    order.payment_status = Order.PaymentStatus.PAID
    order.paid_at = timezone.now()
    order.save(update_fields=["payment_status", "paid_at", "updated_at"])

    _record(
        order,
        OrderEvent.EventType.PAID,
        actor=actor,
        request=request,
        changes={"payment_status": ["unpaid", "paid"], "amount": str(order.total)},
        note=note,
    )
    return order


def balance_for(user):
    """Total the user owes: unpaid orders that haven't been cancelled."""
    unpaid = user.orders.filter(payment_status=Order.PaymentStatus.UNPAID).exclude(status=Order.Status.CANCELLED)
    return {
        # A string like "56.00", matching how DRF serializes the other money fields.
        "balance": str((unpaid.aggregate(total=Sum("total"))["total"] or Decimal("0")).quantize(Decimal("0.01"))),
        "unpaid_orders": unpaid.count(),
    }
