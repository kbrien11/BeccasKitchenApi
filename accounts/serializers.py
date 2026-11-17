
from django.contrib.auth import authenticate
from rest_framework import serializers

from .allergens import ALLERGENS
from .models import Child, Favorite, Order, OrderEvent, OrderItem, User


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "subscription_plan",
        ]
        read_only_fields = ["subscription_plan"]


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["subscription_plan"]
        extra_kwargs = {"subscription_plan": {"required": True}}


class FavoriteSerializer(serializers.ModelSerializer):
    meal_id = serializers.IntegerField(min_value=1)

    class Meta:
        model = Favorite
        fields = ["meal_id", "created_at"]
        read_only_fields = ["created_at"]


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        min_length=8
    )

    class Meta:
        model = User
        fields = [
            "email",
            "first_name",
            "last_name",
            "password",
        ]

    def validate_email(self, value):
        return value.lower().strip()

    def create(self, validated_data):
        password = validated_data.pop("password")

        return User.objects.create_user(
            password=password,
            **validated_data
        )


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email = attrs["email"].lower().strip()

        user = authenticate(
            username=email,
            password=attrs["password"]
        )

        if not user:
            raise serializers.ValidationError({
                "detail": "Invalid email or password."
            })

        if not user.is_active:
            raise serializers.ValidationError({
                "detail": "This account is inactive."
            })

        attrs["user"] = user
        return attrs


class OrderItemInputSerializer(serializers.Serializer):
    meal_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, max_value=50)


class DeliverySerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=30)
    address = serializers.CharField(max_length=255)
    apartment = serializers.CharField(max_length=100, required=False, allow_blank=True)
    city = serializers.CharField(max_length=100)
    state = serializers.CharField(max_length=50)
    zip_code = serializers.CharField(max_length=20)
    delivery_instructions = serializers.CharField(required=False, allow_blank=True)


class OrderCreateSerializer(serializers.Serializer):
    items = OrderItemInputSerializer(many=True, allow_empty=False)
    delivery = DeliverySerializer()


class OrderItemSerializer(serializers.ModelSerializer):
    line_total = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = OrderItem
        fields = ["meal_id", "name", "unit_price", "quantity", "line_total"]


class OrderEventSerializer(serializers.ModelSerializer):
    actor = serializers.SerializerMethodField()

    class Meta:
        model = OrderEvent
        fields = ["id", "event_type", "from_status", "to_status", "actor", "changes", "note", "created_at"]

    def get_actor(self, event):
        """Customers see who acted without exposing staff identities."""
        if event.actor is None:
            return "system"
        request = self.context.get("request")
        if request and event.actor_id == request.user.id:
            return "you"
        return "staff" if event.actor.is_staff else "system"


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    events = OrderEventSerializer(many=True, read_only=True)
    can_cancel = serializers.SerializerMethodField()
    amount_owed = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = Order
        fields = [
            "id",
            "status",
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
            "subtotal",
            "delivery_fee",
            "total",
            "payment_status",
            "paid_at",
            "amount_owed",
            "items",
            "events",
            "can_cancel",
            "created_at",
            "updated_at",
        ]

    def get_can_cancel(self, order):
        return order.status == Order.Status.PENDING


class ChildSerializer(serializers.ModelSerializer):
    allergens = serializers.ListField(
        child=serializers.ChoiceField(choices=list(ALLERGENS.keys())),
        required=False,
    )

    class Meta:
        model = Child
        fields = ["id", "name", "birth_date", "allergens", "allergy_notes", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_allergens(self, value):
        return sorted(set(value))
