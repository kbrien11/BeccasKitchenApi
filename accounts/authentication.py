"""Token auth that expires, and can be read from an httpOnly cookie (with CSRF protection)."""
from django.conf import settings
from django.middleware.csrf import CsrfViewMiddleware
from django.utils import timezone
from rest_framework import exceptions
from rest_framework.authentication import TokenAuthentication


def token_expired(token):
    return timezone.now() - token.created > settings.AUTH_TOKEN_TTL


class ExpiringTokenAuthentication(TokenAuthentication):
    """`Authorization: Token <key>` header auth, but tokens stop working after AUTH_TOKEN_TTL."""

    def authenticate_credentials(self, key):
        user, token = super().authenticate_credentials(key)
        if token_expired(token):
            token.delete()
            raise exceptions.AuthenticationFailed("Your session has expired. Please log in again.")
        return user, token


class _CSRFCheck(CsrfViewMiddleware):
    def _reject(self, request, reason):
        return reason


class CookieTokenAuthentication(ExpiringTokenAuthentication):
    """
    Reads the token from the httpOnly auth cookie the browser app uses.

    Because browsers send cookies automatically, unsafe requests (POST/PATCH/DELETE)
    must also carry a matching CSRF token, just like Django session auth.
    """

    def authenticate(self, request):
        key = request.COOKIES.get(settings.AUTH_COOKIE_NAME)
        if not key:
            return None  # Fall through to header auth.

        user, token = self.authenticate_credentials(key)
        self.enforce_csrf(request)
        return user, token

    def enforce_csrf(self, request):
        check = _CSRFCheck(lambda req: None)
        check.process_request(request)
        reason = check.process_view(request, None, (), {})
        if reason:
            raise exceptions.PermissionDenied(f"CSRF Failed: {reason}")
