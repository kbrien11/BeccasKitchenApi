from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from .models import User

FAVORITES_URL = "/api/auth/me/favorites/"


class FavoritesApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="parent@example.test", password="test-pass-123")
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def favorite_ids(self):
        return [f["meal_id"] for f in self.client.get(FAVORITES_URL).data["favorites"]]

    def test_requires_auth(self):
        self.client.credentials()
        self.assertEqual(self.client.get(FAVORITES_URL).status_code, 401)

    def test_add_list_and_remove(self):
        self.assertEqual(self.client.post(FAVORITES_URL, {"meal_id": 3}).status_code, 201)
        self.assertEqual(self.client.post(FAVORITES_URL, {"meal_id": 3}).status_code, 200)
        self.client.post(FAVORITES_URL, {"meal_id": 5})
        self.assertEqual(self.favorite_ids(), [5, 3])

        self.assertEqual(self.client.delete(f"{FAVORITES_URL}3/").status_code, 204)
        self.assertEqual(self.favorite_ids(), [5])

    def test_rejects_invalid_meal_id(self):
        self.assertEqual(self.client.post(FAVORITES_URL, {"meal_id": 0}).status_code, 400)
        self.assertEqual(self.client.post(FAVORITES_URL, {}).status_code, 400)

    def test_users_only_see_their_own(self):
        other = User.objects.create_user(email="other@example.test", password="test-pass-123")
        other.favorites.create(meal_id=1)
        self.assertEqual(self.favorite_ids(), [])


ORDERS_URL = "/api/auth/me/orders/"

DELIVERY = {
    "first_name": "Test",
    "last_name": "Parent",
    "email": "parent@example.test",
    "phone": "516-555-0100",
    "address": "1 Main St",
    "city": "Great Neck",
    "state": "NY",
    "zip_code": "11021",
}


class OrdersApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="parent@example.test", password="test-pass-123")
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def place(self, items=None):
        return self.client.post(
            ORDERS_URL,
            {"items": items or [{"meal_id": 1, "quantity": 2}], "delivery": DELIVERY},
            format="json",
        )

    def test_place_order_uses_server_prices_and_audits_creation(self):
        response = self.place([{"meal_id": 1, "quantity": 2}, {"meal_id": 3, "quantity": 1}, {"meal_id": 1, "quantity": 1}])
        self.assertEqual(response.status_code, 201)
        data = response.data

        # 3 x 5.50 + 1 x 6.00 = 22.50, under $50 so $5 delivery.
        self.assertEqual(data["subtotal"], "22.50")
        self.assertEqual(data["delivery_fee"], "5.00")
        self.assertEqual(data["total"], "27.50")
        self.assertEqual({i["meal_id"]: i["quantity"] for i in data["items"]}, {1: 3, 3: 1})

        self.assertEqual(len(data["events"]), 1)
        event = data["events"][0]
        self.assertEqual(event["event_type"], "created")
        self.assertEqual(event["to_status"], "pending")
        self.assertEqual(event["actor"], "you")
        self.assertEqual(event["changes"]["total"], "27.50")

    def test_free_delivery_over_minimum(self):
        data = self.place([{"meal_id": 4, "quantity": 8}]).data  # $56
        self.assertEqual(data["delivery_fee"], "0.00")

    def test_rejects_unknown_meal_and_empty_order(self):
        self.assertEqual(self.place([{"meal_id": 999, "quantity": 1}]).status_code, 400)
        response = self.client.post(ORDERS_URL, {"items": [], "delivery": DELIVERY}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_cancel_pending_order_is_audited(self):
        order_id = self.place().data["id"]
        response = self.client.post(f"{ORDERS_URL}{order_id}/cancel/", {"reason": "Ordered twice"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "cancelled")

        event = response.data["events"][-1]
        self.assertEqual(event["event_type"], "cancelled")
        self.assertEqual((event["from_status"], event["to_status"]), ("pending", "cancelled"))
        self.assertEqual(event["note"], "Ordered twice")

    def test_cannot_cancel_after_confirmation(self):
        from .models import Order
        from .orders import change_status

        order = Order.objects.get(pk=self.place().data["id"])
        change_status(order, Order.Status.CONFIRMED)
        response = self.client.post(f"{ORDERS_URL}{order.pk}/cancel/")
        self.assertEqual(response.status_code, 400)

    def test_invalid_status_transition_is_rejected(self):
        from .models import Order
        from .orders import OrderError, change_status

        order = Order.objects.get(pk=self.place().data["id"])
        with self.assertRaises(OrderError):
            change_status(order, Order.Status.DELIVERED)
        self.assertEqual(order.events.count(), 1)

    def test_audit_events_are_append_only(self):
        from .models import Order

        event = Order.objects.get(pk=self.place().data["id"]).events.first()
        event.note = "tampered"
        with self.assertRaises(ValueError):
            event.save()
        with self.assertRaises(ValueError):
            event.delete()

    def test_users_only_see_their_own_orders(self):
        order_id = self.place().data["id"]
        other = User.objects.create_user(email="other@example.test", password="test-pass-123")
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=other).key}")
        self.assertEqual(self.client.get(ORDERS_URL).data["orders"], [])
        self.assertEqual(self.client.get(f"{ORDERS_URL}{order_id}/").status_code, 404)
        self.assertEqual(self.client.post(f"{ORDERS_URL}{order_id}/cancel/").status_code, 404)


class OrderAdminAuditTests(APITestCase):
    def test_admin_edits_are_audited_with_staff_actor(self):
        from django.test import Client

        from .models import Order
        from .orders import place_order

        customer = User.objects.create_user(email="parent@example.test", password="test-pass-123")
        order = place_order(customer, [{"meal_id": 2, "quantity": 1}], DELIVERY)
        staff = User.objects.create_superuser(email="becca@example.test", password="test-pass-123")

        browser = Client()
        browser.force_login(staff)
        form = {**DELIVERY, "status": "confirmed", "phone": "516-555-0199", "apartment": "", "delivery_instructions": ""}
        # Inline management forms for items and events (no changes to either).
        for prefix, count in [("items", 1), ("events", 1)]:
            form.update({
                f"{prefix}-TOTAL_FORMS": str(count),
                f"{prefix}-INITIAL_FORMS": str(count),
                f"{prefix}-MIN_NUM_FORMS": "0",
                f"{prefix}-MAX_NUM_FORMS": "1000",
            })
        form["items-0-id"] = str(order.items.first().pk)
        form["items-0-order"] = str(order.pk)
        form["events-0-id"] = str(order.events.first().pk)
        form["events-0-order"] = str(order.pk)

        response = browser.post(f"/admin/accounts/order/{order.pk}/change/", form)
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context.get("errors"))

        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CONFIRMED)
        updated, status_changed = order.events.order_by("id")[1:]
        self.assertEqual(updated.event_type, "updated")
        self.assertEqual(updated.changes, {"phone": ["516-555-0100", "516-555-0199"]})
        self.assertEqual(updated.actor, staff)
        self.assertEqual(status_changed.event_type, "status_changed")
        self.assertEqual((status_changed.from_status, status_changed.to_status), ("pending", "confirmed"))
        self.assertEqual(status_changed.actor, staff)


class BalanceTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="parent@example.test", password="test-pass-123")
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.user).key}")

    def place(self, meal_id, quantity):
        from .orders import place_order

        return place_order(self.user, [{"meal_id": meal_id, "quantity": quantity}], DELIVERY)

    def test_balance_counts_unpaid_uncancelled_orders(self):
        from .models import Order
        from .orders import change_status, mark_paid

        a = self.place(1, 2)  # 11.00 + 5.00 = 16.00
        b = self.place(3, 1)  # 6.00 + 5.00 = 11.00
        c = self.place(4, 8)  # 56.00, free delivery

        data = self.client.get("/api/auth/me/balance/").data
        self.assertEqual((str(data["balance"]), data["unpaid_orders"]), ("83.00", 3))

        change_status(b, Order.Status.CANCELLED)
        mark_paid(c)
        data = self.client.get("/api/auth/me/balance/").data
        self.assertEqual((str(data["balance"]), data["unpaid_orders"]), ("16.00", 1))

        listing = self.client.get(ORDERS_URL).data
        self.assertEqual(str(listing["balance"]), "16.00")
        owed = {o["id"]: o["amount_owed"] for o in listing["orders"]}
        self.assertEqual(owed, {a.pk: "16.00", b.pk: "0.00", c.pk: "0.00"})

    def test_mark_paid_is_audited_and_blocked_for_cancelled(self):
        from .models import Order
        from .orders import OrderError, change_status, mark_paid

        order = mark_paid(self.place(2, 1), note="Cash on delivery")
        event = order.events.last()
        self.assertEqual(event.event_type, "paid")
        self.assertEqual(event.changes, {"payment_status": ["unpaid", "paid"], "amount": "10.50"})
        self.assertIsNotNone(order.paid_at)

        cancelled = change_status(self.place(2, 1), Order.Status.CANCELLED)
        with self.assertRaises(OrderError):
            mark_paid(cancelled)


CHILDREN_URL = "/api/auth/me/children/"


class ChildrenApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="parent@example.test", password="test-pass-123")
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.user).key}")

    def test_add_update_and_remove_child_allergies(self):
        response = self.client.post(
            CHILDREN_URL, {"name": "Ava", "allergens": ["peanut", "milk", "milk"]}, format="json"
        )
        self.assertEqual(response.status_code, 201)
        child_id = response.data["id"]
        self.assertEqual(response.data["allergens"], ["milk", "peanut"])

        response = self.client.patch(
            f"{CHILDREN_URL}{child_id}/", {"allergens": ["egg"], "allergy_notes": "Mild"}, format="json"
        )
        self.assertEqual(response.data["allergens"], ["egg"])
        self.assertEqual(self.client.get(CHILDREN_URL).data["children"][0]["allergy_notes"], "Mild")

        self.assertEqual(self.client.delete(f"{CHILDREN_URL}{child_id}/").status_code, 204)
        self.assertEqual(self.client.get(CHILDREN_URL).data["children"], [])

    def test_rejects_unknown_allergen(self):
        response = self.client.post(CHILDREN_URL, {"name": "Ava", "allergens": ["chocolate"]}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_users_only_manage_their_own_children(self):
        other = User.objects.create_user(email="other@example.test", password="test-pass-123")
        child = other.children.create(name="Theo", allergens=["egg"])
        self.assertEqual(self.client.get(CHILDREN_URL).data["children"], [])
        self.assertEqual(self.client.patch(f"{CHILDREN_URL}{child.pk}/", {"name": "x"}).status_code, 404)
        self.assertEqual(self.client.delete(f"{CHILDREN_URL}{child.pk}/").status_code, 404)

    def test_allergen_list_is_public(self):
        self.client.credentials()
        data = self.client.get("/api/auth/allergens/").data["allergens"]
        self.assertEqual(data["tree_nut"], "Tree nuts")


class TastingsApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="parent@example.test", password="test-pass-123")
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.user).key}")
        self.child = self.user.children.create(name="Ava", allergens=["milk"])
        self.url = f"/api/auth/me/children/{self.child.pk}/tastings/"

    def test_log_list_and_delete_tastings(self):
        first = self.client.post(self.url, {"meal_id": 1, "reaction": "disliked", "tried_on": "2026-09-01"}, format="json")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.data["meal_name"], "Sunny Sweet Potato")
        # Same meal again later: kept as history, not overwritten.
        self.client.post(self.url, {"meal_id": 1, "reaction": "loved", "tried_on": "2026-10-01", "note": "Asked for more"}, format="json")

        tastings = self.client.get(self.url).data["tastings"]
        self.assertEqual([t["reaction"] for t in tastings], ["loved", "disliked"])
        self.assertEqual(tastings[0]["note"], "Asked for more")

        all_tastings = self.client.get("/api/auth/me/tastings/").data["tastings"]
        self.assertEqual(len(all_tastings), 2)
        self.assertEqual(all_tastings[0]["child_id"], self.child.pk)

        self.assertEqual(self.client.delete(f"{self.url}{first.data['id']}/").status_code, 204)
        self.assertEqual(len(self.client.get(self.url).data["tastings"]), 1)

    def test_validation(self):
        bad_meal = self.client.post(self.url, {"meal_id": 999, "reaction": "loved", "tried_on": "2026-09-01"}, format="json")
        bad_reaction = self.client.post(self.url, {"meal_id": 1, "reaction": "meh", "tried_on": "2026-09-01"}, format="json")
        future = self.client.post(self.url, {"meal_id": 1, "reaction": "loved", "tried_on": "2999-01-01"}, format="json")
        self.assertEqual([bad_meal.status_code, bad_reaction.status_code, future.status_code], [400, 400, 400])

    def test_cannot_touch_another_familys_child(self):
        other = User.objects.create_user(email="other@example.test", password="test-pass-123")
        theirs = other.children.create(name="Theo")
        tasting = theirs.tastings.create(meal_id=1, reaction="loved", tried_on="2026-09-01")
        url = f"/api/auth/me/children/{theirs.pk}/tastings/"

        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, {"meal_id": 1, "reaction": "loved", "tried_on": "2026-09-01"}, format="json").status_code, 404)
        self.assertEqual(self.client.delete(f"{url}{tasting.pk}/").status_code, 404)
        self.assertEqual(self.client.get("/api/auth/me/tastings/").data["tastings"], [])


class CookieAuthTests(APITestCase):
    """The browser app's flow: httpOnly auth cookie + CSRF token, no token in JS."""

    def setUp(self):
        from rest_framework.test import APIClient

        self.browser = APIClient(enforce_csrf_checks=True)
        self.user = User.objects.create_user(email="parent@example.test", password="test-pass-123")

    def login(self):
        return self.browser.post("/api/auth/login/", {"email": "parent@example.test", "password": "test-pass-123"}, format="json")

    def csrf(self):
        self.browser.get("/api/auth/csrf/")
        return self.browser.cookies["csrftoken"].value

    def test_login_sets_httponly_cookie_and_hides_token(self):
        response = self.login()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("token", response.data)

        cookie = response.cookies["bk_auth"]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")
        self.assertEqual(cookie.value, Token.objects.get(user=self.user).key)

        me = self.browser.get("/api/auth/me/")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.data["user"]["email"], "parent@example.test")

    def test_register_sets_cookie(self):
        response = self.browser.post(
            "/api/auth/register/",
            {"email": "new@example.test", "first_name": "N", "last_name": "P", "password": "long-enough-1"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertNotIn("token", response.data)
        self.assertTrue(response.cookies["bk_auth"]["httponly"])

    def test_unsafe_requests_need_csrf_token(self):
        self.login()
        url = "/api/auth/me/favorites/"

        blocked = self.browser.post(url, {"meal_id": 1}, format="json")
        self.assertEqual(blocked.status_code, 403)
        self.assertIn("CSRF", str(blocked.data["detail"]))

        allowed = self.browser.post(url, {"meal_id": 1}, format="json", HTTP_X_CSRFTOKEN=self.csrf())
        self.assertEqual(allowed.status_code, 201)

    def test_logout_revokes_token_and_clears_cookie(self):
        self.login()
        response = self.browser.post("/api/auth/logout/", HTTP_X_CSRFTOKEN=self.csrf())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.cookies["bk_auth"].value, "")
        self.assertFalse(Token.objects.filter(user=self.user).exists())
        self.assertEqual(self.browser.get("/api/auth/me/").status_code, 401)

    def test_logout_without_csrf_is_rejected(self):
        self.login()
        self.assertEqual(self.browser.post("/api/auth/logout/").status_code, 403)
        self.assertTrue(Token.objects.filter(user=self.user).exists())

    def test_expired_token_is_rejected_and_replaced_on_login(self):
        from datetime import timedelta

        from django.utils import timezone

        self.login()
        old = Token.objects.get(user=self.user)
        Token.objects.filter(pk=old.pk).update(created=timezone.now() - timedelta(days=15))

        self.assertEqual(self.browser.get("/api/auth/me/").status_code, 401)
        self.assertFalse(Token.objects.filter(pk=old.pk).exists())

        # Logging out with the dead cookie still clears it.
        self.assertEqual(self.browser.post("/api/auth/logout/", HTTP_X_CSRFTOKEN=self.csrf()).status_code, 200)

        self.login()
        self.assertNotEqual(Token.objects.get(user=self.user).key, old.key)

    def test_expired_header_token_is_rejected(self):
        from datetime import timedelta

        from django.utils import timezone

        token = Token.objects.create(user=self.user)
        Token.objects.filter(pk=token.pk).update(created=timezone.now() - timedelta(days=15))
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)
