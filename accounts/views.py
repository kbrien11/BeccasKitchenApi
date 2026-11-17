from django.shortcuts import render

# Create your views here.

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.authtoken.models import Token

from .serializers import (
    RegisterSerializer,
    LoginSerializer,
    UserSerializer,
    SubscriptionPlanSerializer,
    FavoriteSerializer,
    OrderCreateSerializer,
    OrderSerializer,
    ChildSerializer,
)
from .allergens import ALLERGENS
from .models import Favorite, Order
from .orders import OrderError, balance_for, change_status, place_order


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)

        if serializer.is_valid():
            user = serializer.save()

            token, _ = Token.objects.get_or_create(user=user)

            return Response({
                "message": "Account created successfully.",
                "token": token.key,
                "user": UserSerializer(user).data
            }, status=status.HTTP_201_CREATED)

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)

        if serializer.is_valid():
            user = serializer.validated_data["user"]

            token, _ = Token.objects.get_or_create(user=user)

            return Response({
                "message": "Login successful.",
                "token": token.key,
                "user": UserSerializer(user).data
            }, status=status.HTTP_200_OK)

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        request.user.auth_token.delete()

        return Response({
            "message": "Logged out successfully."
        }, status=status.HTTP_200_OK)


class CurrentUserView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({
            "user": UserSerializer(request.user).data
        })


class SubscriptionPlanView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request):
        serializer = SubscriptionPlanSerializer(
            request.user,
            data=request.data
        )

        if serializer.is_valid():
            user = serializer.save()

            return Response({
                "message": "Subscription plan updated.",
                "user": UserSerializer(user).data
            }, status=status.HTTP_200_OK)

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )


class FavoriteListView(APIView):
    """GET: the user's favorites (newest first). POST {meal_id}: save a meal."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        favorites = request.user.favorites.all()
        return Response({"favorites": FavoriteSerializer(favorites, many=True).data})

    def post(self, request):
        serializer = FavoriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        favorite, created = Favorite.objects.get_or_create(
            user=request.user,
            meal_id=serializer.validated_data["meal_id"],
        )

        return Response(
            FavoriteSerializer(favorite).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class FavoriteDetailView(APIView):
    """DELETE: remove a saved meal. Removing one that isn't saved is a no-op."""

    permission_classes = [IsAuthenticated]

    def delete(self, request, meal_id):
        request.user.favorites.filter(meal_id=meal_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


def _orders_for(user):
    return user.orders.prefetch_related("items", "events__actor")


class OrderListView(APIView):
    """GET: the user's orders (newest first). POST: place a one-time order."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        orders = _orders_for(request.user)
        return Response({
            "orders": OrderSerializer(orders, many=True, context={"request": request}).data,
            **balance_for(request.user),
        })

    def post(self, request):
        serializer = OrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            order = place_order(
                request.user,
                serializer.validated_data["items"],
                serializer.validated_data["delivery"],
                request=request,
            )
        except OrderError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)

        order = _orders_for(request.user).get(pk=order.pk)
        return Response(
            OrderSerializer(order, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class OrderDetailView(APIView):
    """GET: one of the user's orders, including its audit history."""

    permission_classes = [IsAuthenticated]

    def get(self, request, order_id):
        order = _orders_for(request.user).filter(pk=order_id).first()
        if order is None:
            return Response({"detail": "Order not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(OrderSerializer(order, context={"request": request}).data)


class OrderCancelView(APIView):
    """POST: cancel one of the user's orders while it is still pending."""

    permission_classes = [IsAuthenticated]

    def post(self, request, order_id):
        order = request.user.orders.filter(pk=order_id).first()
        if order is None:
            return Response({"detail": "Order not found."}, status=status.HTTP_404_NOT_FOUND)
        if order.status != Order.Status.PENDING:
            return Response(
                {"detail": "This order can no longer be cancelled."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        change_status(
            order,
            Order.Status.CANCELLED,
            actor=request.user,
            request=request,
            note=request.data.get("reason", "")[:255],
        )
        order = _orders_for(request.user).get(pk=order.pk)
        return Response(OrderSerializer(order, context={"request": request}).data)


class BalanceView(APIView):
    """GET: how much the user owes across unpaid, non-cancelled orders."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(balance_for(request.user))


class AllergenListView(APIView):
    """GET: the allergens the kitchen tracks, as {code: label}."""

    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"allergens": ALLERGENS})


class ChildListView(APIView):
    """GET: the user's little ones. POST: add one."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"children": ChildSerializer(request.user.children.all(), many=True).data})

    def post(self, request):
        serializer = ChildSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(user=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ChildDetailView(APIView):
    """PATCH: update a little one (e.g. their allergies). DELETE: remove them."""

    permission_classes = [IsAuthenticated]

    def _get(self, request, child_id):
        return request.user.children.filter(pk=child_id).first()

    def patch(self, request, child_id):
        child = self._get(request, child_id)
        if child is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = ChildSerializer(child, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, child_id):
        child = self._get(request, child_id)
        if child is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        child.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
