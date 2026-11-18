
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class CustomUserManager(BaseUserManager):

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required")

        email = self.normalize_email(email)

        user = self.model(
            email=email,
            **extra_fields
        )

        user.set_password(password)
        user.save(using=self._db)

        return user

    def create_superuser(self, email, password=None, **extra_fields):

        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True")

        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True")

        return self.create_user(email, password, **extra_fields)


class User(AbstractUser):

    class SubscriptionPlan(models.TextChoices):
        FREE = "free", "Free"
        BASIC = "basic", "Basic"
        PREMIUM = "premium", "Premium"

    username = None

    email = models.EmailField(unique=True)

    subscription_plan = models.CharField(
        max_length=20,
        choices=SubscriptionPlan.choices,
        default=SubscriptionPlan.FREE,
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = CustomUserManager()

    def __str__(self):
        return self.email


class Favorite(models.Model):
    """A meal a user has saved. Meals live in the UI for now, so we store the meal id."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="favorites",
    )
    meal_id = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "meal_id"],
                name="unique_favorite_per_user",
            )
        ]

    def __str__(self):
        return f"{self.user} - meal {self.meal_id}"


class Order(models.Model):
    """A one-time order. Every change to it is recorded as an OrderEvent."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        OUT_FOR_DELIVERY = "out_for_delivery", "Out for delivery"
        DELIVERED = "delivered", "Delivered"
        CANCELLED = "cancelled", "Cancelled"

    # Which status changes are allowed, from -> to.
    TRANSITIONS = {
        Status.PENDING: {Status.CONFIRMED, Status.CANCELLED},
        Status.CONFIRMED: {Status.OUT_FOR_DELIVERY, Status.CANCELLED},
        Status.OUT_FOR_DELIVERY: {Status.DELIVERED},
        Status.DELIVERED: set(),
        Status.CANCELLED: set(),
    }

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="orders",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=30)
    address = models.CharField(max_length=255)
    apartment = models.CharField(max_length=100, blank=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=50)
    zip_code = models.CharField(max_length=20)
    delivery_instructions = models.TextField(blank=True)

    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2)
    total = models.DecimalField(max_digits=10, decimal_places=2)

    class PaymentStatus(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PAID = "paid", "Paid"

    payment_status = models.CharField(
        max_length=10,
        choices=PaymentStatus.choices,
        default=PaymentStatus.UNPAID,
    )
    paid_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Order #{self.pk} ({self.get_status_display()})"

    @property
    def amount_owed(self):
        """What the customer still owes on this order. Cancelled and paid orders owe nothing."""
        if self.status == self.Status.CANCELLED or self.payment_status == self.PaymentStatus.PAID:
            return Decimal("0.00")
        return self.total

    def can_transition_to(self, new_status):
        return new_status in self.TRANSITIONS.get(self.status, set())


class OrderItem(models.Model):
    """A line on an order. Name and price are snapshotted so later menu changes don't rewrite history."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    meal_id = models.PositiveIntegerField()
    name = models.CharField(max_length=200)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField()

    @property
    def line_total(self):
        return self.unit_price * self.quantity

    def __str__(self):
        return f"{self.quantity} x {self.name}"


class OrderEvent(models.Model):
    """Append-only audit log entry for an order. Rows can be created but never edited or deleted."""

    class EventType(models.TextChoices):
        CREATED = "created", "Created"
        STATUS_CHANGED = "status_changed", "Status changed"
        UPDATED = "updated", "Updated"
        CANCELLED = "cancelled", "Cancelled"
        PAID = "paid", "Payment recorded"

    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="events")
    event_type = models.CharField(max_length=20, choices=EventType.choices)
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20, blank=True)
    # Who made the change. Null means the system did it.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order_events",
    )
    # Field-level before/after values, e.g. {"phone": ["555-0100", "555-0199"]}, or a snapshot on create.
    changes = models.JSONField(default=dict, blank=True)
    note = models.CharField(max_length=255, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"Order #{self.order_id}: {self.get_event_type_display()}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError("Order audit events are append-only and cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Order audit events are append-only and cannot be deleted.")


def validate_allergens(value):
    from .allergens import ALLERGEN_CODES

    if not isinstance(value, list) or any(code not in ALLERGEN_CODES for code in value):
        raise ValidationError(f"Allergens must be a list of: {', '.join(sorted(ALLERGEN_CODES))}.")


class Child(models.Model):
    """A little one on the account, with the allergies we should warn about."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="children",
    )
    name = models.CharField(max_length=100)
    birth_date = models.DateField(null=True, blank=True)
    # Allergen codes from accounts/allergens.py, e.g. ["milk", "peanut"].
    allergens = models.JSONField(default=list, blank=True, validators=[validate_allergens])
    allergy_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name_plural = "children"

    def __str__(self):
        return f"{self.name} ({self.user})"


class MealTasting(models.Model):
    """One time a child tried a meal, and how it went. Kept as a history (a meal can be tried many times)."""

    class Reaction(models.TextChoices):
        LOVED = "loved", "Loved it"
        OKAY = "okay", "It was okay"
        DISLIKED = "disliked", "Not a fan"
        REACTION = "reaction", "Had a reaction"

    child = models.ForeignKey(Child, on_delete=models.CASCADE, related_name="tastings")
    meal_id = models.PositiveIntegerField()
    reaction = models.CharField(max_length=10, choices=Reaction.choices)
    note = models.CharField(max_length=500, blank=True)
    tried_on = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-tried_on", "-created_at"]

    def __str__(self):
        return f"{self.child.name} - meal {self.meal_id}: {self.reaction}"
