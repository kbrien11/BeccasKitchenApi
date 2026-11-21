"""Rate limits for the sign-in endpoints (brute-force and spam-signup protection).

Rates live in settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"].
"""

from rest_framework.throttling import SimpleRateThrottle


class LoginEmailThrottle(SimpleRateThrottle):
    """Login attempts per account email, whatever IP they come from.

    Per-IP limits alone can be dodged by rotating IPs or spoofing
    X-Forwarded-For, so password guessing against one account is capped here too.
    """

    scope = "login_email"

    def get_cache_key(self, request, view):
        email = request.data.get("email") if hasattr(request, "data") else None
        if not isinstance(email, str) or not email.strip():
            return None  # Nothing to key on; the per-IP limit still applies.
        return self.cache_format % {"scope": self.scope, "ident": email.strip().lower()}
