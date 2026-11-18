from django.contrib import admin, messages

from .models import Child, Favorite, MealTasting, Order, OrderEvent, OrderItem
from .orders import DELIVERY_FIELDS, OrderError, change_status, mark_paid, record_field_changes


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    readonly_fields = ["meal_id", "name", "unit_price", "quantity"]

    def has_add_permission(self, request, obj=None):
        return False


class OrderEventInline(admin.TabularInline):
    """Read-only audit trail shown on each order."""

    model = OrderEvent
    extra = 0
    can_delete = False
    fields = ["created_at", "event_type", "from_status", "to_status", "actor", "changes", "note", "ip_address"]
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ["id", "user", "status", "payment_status", "total", "created_at"]
    list_filter = ["status", "payment_status", "created_at"]
    search_fields = ["id", "user__email", "last_name", "address"]
    readonly_fields = [
        "user",
        "subtotal",
        "delivery_fee",
        "total",
        "payment_status",
        "paid_at",
        "created_at",
        "updated_at",
    ]
    inlines = [OrderItemInline, OrderEventInline]
    actions = ["mark_selected_paid"]

    @admin.action(description="Mark selected orders as paid")
    def mark_selected_paid(self, request, queryset):
        paid, skipped = 0, 0
        for order in queryset:
            try:
                mark_paid(order, actor=request.user, request=request, note="Marked paid in admin")
                paid += 1
            except OrderError:
                skipped += 1
        self.message_user(request, f"Marked {paid} order(s) as paid.")
        if skipped:
            self.message_user(request, f"Skipped {skipped} cancelled order(s).", messages.WARNING)

    def has_add_permission(self, request):
        return False  # Orders are placed through the API so they always get a "created" event.

    def has_delete_permission(self, request, obj=None):
        return False  # Keep the audit trail intact.

    def save_model(self, request, obj, form, change):
        """Route admin edits through the audited order functions instead of saving directly."""
        original = Order.objects.get(pk=obj.pk)
        before = {field: getattr(original, field) for field in DELIVERY_FIELDS}
        new_status = obj.status

        # Save field edits (but not status) first, then audit them.
        obj.status = original.status
        obj.save()
        record_field_changes(obj, before, actor=request.user, request=request, note="Edited in admin")

        if new_status != original.status:
            try:
                change_status(obj, new_status, actor=request.user, request=request, note="Changed in admin")
            except OrderError as error:
                messages.error(request, str(error))


@admin.register(OrderEvent)
class OrderEventAdmin(admin.ModelAdmin):
    """Searchable, read-only view of the whole audit log."""

    list_display = ["created_at", "order", "event_type", "from_status", "to_status", "actor"]
    list_filter = ["event_type", "created_at"]
    search_fields = ["order__id", "actor__email"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Favorite)
class FavoriteAdmin(admin.ModelAdmin):
    list_display = ["user", "meal_id", "created_at"]
    search_fields = ["user__email"]


class MealTastingInline(admin.TabularInline):
    model = MealTasting
    extra = 0
    fields = ["tried_on", "meal_id", "reaction", "note"]


@admin.register(Child)
class ChildAdmin(admin.ModelAdmin):
    list_display = ["name", "user", "allergens", "created_at"]
    search_fields = ["name", "user__email"]
    inlines = [MealTastingInline]
