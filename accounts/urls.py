
from django.urls import path

from .views import (
    RegisterView,
    LoginView,
    LogoutView,
    CsrfView,
    CurrentUserView,
    SubscriptionPlanView,
    FavoriteListView,
    FavoriteDetailView,
    OrderListView,
    OrderDetailView,
    OrderCancelView,
    BalanceView,
    AllergenListView,
    ChildListView,
    ChildDetailView,
    ChildTastingListView,
    ChildTastingDetailView,
    TastingListView,
)

urlpatterns = [
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("csrf/", CsrfView.as_view(), name="csrf"),
    path("me/", CurrentUserView.as_view(), name="current-user"),
    path(
        "me/subscription/",
        SubscriptionPlanView.as_view(),
        name="subscription-plan"
    ),
    path("me/favorites/", FavoriteListView.as_view(), name="favorite-list"),
    path(
        "me/favorites/<int:meal_id>/",
        FavoriteDetailView.as_view(),
        name="favorite-detail"
    ),
    path("me/orders/", OrderListView.as_view(), name="order-list"),
    path("me/orders/<int:order_id>/", OrderDetailView.as_view(), name="order-detail"),
    path(
        "me/orders/<int:order_id>/cancel/",
        OrderCancelView.as_view(),
        name="order-cancel"
    ),
    path("me/balance/", BalanceView.as_view(), name="balance"),
    path("me/children/", ChildListView.as_view(), name="child-list"),
    path("me/children/<int:child_id>/", ChildDetailView.as_view(), name="child-detail"),
    path("allergens/", AllergenListView.as_view(), name="allergens"),
    path("me/children/<int:child_id>/tastings/", ChildTastingListView.as_view(), name="child-tasting-list"),
    path(
        "me/children/<int:child_id>/tastings/<int:tasting_id>/",
        ChildTastingDetailView.as_view(),
        name="child-tasting-detail"
    ),
    path("me/tastings/", TastingListView.as_view(), name="tasting-list"),
]
